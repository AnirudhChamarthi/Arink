"""``RubricAssessor``: implements ``contract.ports.Assessor``.

* ``assess`` evaluates every row of the question's rubric table. A rule returns likelihood, impact,
  control, a rationale and evidence (``source="rule"``); a rule whose inputs are missing raises
  ``MissingInput`` and the factor is ``source="unassessed"`` with likelihood = impact = 3, control
  adequate, and a rationale naming what was missing. Ratings come from ``rules.rate`` and the overall
  rating from ``rules.overall_rating`` (the worst residual).
* ``apply_edits`` applies analyst edits to a copy, logs one ``Override`` per changed field and
  recomputes ratings. It never mutates its input.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

from riskbot.contract import rules
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.types import (
    Comparison,
    ControlStrength,
    Evidence,
    FactorEdit,
    FactorSource,
    Override,
    QualitativeAssessment,
    QualitativeFactor,
    QuestionId,
    VariationResult,
)

from ._base import FactorDef
from ._inputs import Inputs, MissingInput
from .rubrics import RUBRICS

_DATASET_KIND = {QuestionId.Q1: "market", QuestionId.Q2: "balance_sheet", QuestionId.Q3: "climate"}
_EDITABLE = ("likelihood", "impact", "control", "rationale")

METHOD_NOTE = (
    "Judgment, not measurement. Each factor is pre-filled by a deterministic, documented rule that maps "
    "model metrics, data-quality findings, the cross-variation comparison and dataset fields to a likelihood "
    "(1-5), an impact (1-5) and a control strength, citing the evidence used. Inherent rating = likelihood x "
    "impact (1-4 low, 5-9 medium, 10-15 high, 16-25 critical); residual rating lowers it one level for adequate "
    "and two for strong controls; the overall rating is the worst residual. Factors whose inputs were missing "
    "are marked unassessed (likelihood 3, impact 3, adequate) and must be reviewed. Thresholds are expert "
    "conventions, not calibrated probabilities; an analyst may override any factor, and every change is logged."
)


def _unassessed(fd: FactorDef, what: str, evidence: list[Evidence]) -> QualitativeFactor:
    inh, res = rules.rate(3, 3, ControlStrength.ADEQUATE)
    ev = list(evidence) + [Evidence(kind="note", ref=f"missing:{fd.factor_id}", description=f"Missing: {what}.")]
    return QualitativeFactor(
        factor_id=fd.factor_id, name=fd.name, description=fd.description, likelihood=3, impact=3,
        control=ControlStrength.ADEQUATE, inherent=inh, residual=res, evidence=ev,
        rationale=f"Not assessed by rule because an input is missing: {what}. Neutral placeholder ratings "
                  f"need analyst review.",
        source=FactorSource.UNASSESSED,
    )


class RubricAssessor:
    """Rubric-driven assessor. ``rubrics`` maps each question to its tuple of ``FactorDef`` rows."""

    def __init__(self, rubrics: Mapping[QuestionId, tuple[FactorDef, ...]] = RUBRICS) -> None:
        self.rubrics = rubrics

    # -- assess --------------------------------------------------------------------------------

    def assess(self, question: QuestionId, dataset: Any, results: list[VariationResult],
               comparison: Comparison) -> QualitativeAssessment:
        question = QuestionId(question)
        if question not in self.rubrics:
            raise ValidationFailed(f"no rubric for question {question.value!r}")
        kind = getattr(dataset, "kind", None)
        if kind != _DATASET_KIND[question]:
            raise ValidationFailed(f"question {question.value} needs a {_DATASET_KIND[question]} dataset, got {kind!r}")
        if comparison.question != question:
            raise ValidationFailed(f"comparison is for {comparison.question.value}, not {question.value}")
        inp = Inputs(question, dataset, results, comparison)
        factors = [self._evaluate(fd, inp) for fd in self.rubrics[question]]
        return QualitativeAssessment(question=question, factors=factors,
                                     overall=rules.overall_rating([f.residual for f in factors]),
                                     method_note=METHOD_NOTE)

    @staticmethod
    def _evaluate(fd: FactorDef, inp: Inputs) -> QualitativeFactor:
        try:
            out = fd.rule(inp, fd)
        except MissingInput as missing:
            return _unassessed(fd, missing.what, missing.evidence)
        inh, res = rules.rate(out.likelihood, out.impact, out.control)
        return QualitativeFactor(
            factor_id=fd.factor_id, name=fd.name, description=fd.description, likelihood=out.likelihood,
            impact=out.impact, control=out.control, inherent=inh, residual=res, evidence=list(out.evidence),
            rationale=out.rationale, source=FactorSource.RULE,
        )

    # -- apply_edits ---------------------------------------------------------------------------

    def apply_edits(self, assessment: QualitativeAssessment, edits: list[FactorEdit], reviewer: str,
                    at: dt.datetime) -> QualitativeAssessment:
        """Apply edits in order. Validation happens first, so a bad edit changes nothing.

        Only fields whose value actually changes are logged; a factor is marked ``analyst`` once any of
        its fields changed. ``at`` must be timezone-aware (stored as UTC).
        """
        if not reviewer or not reviewer.strip():
            raise ValidationFailed("reviewer is required")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValidationFailed("'at' must be timezone-aware (UTC)")
        at = at.astimezone(dt.timezone.utc)
        parsed = [e if isinstance(e, FactorEdit) else FactorEdit.model_validate(e) for e in edits]
        known = {f.factor_id for f in assessment.factors}
        unknown = sorted({e.factor_id for e in parsed} - known)
        if unknown:
            raise ValidationFailed(f"unknown factor id(s): {unknown}", factor_ids=unknown)

        factors = {f.factor_id: f.model_copy(deep=True) for f in assessment.factors}
        overrides = [o.model_copy(deep=True) for o in assessment.overrides]
        for e in parsed:
            f = factors[e.factor_id]
            changes: dict[str, Any] = {}
            for name in _EDITABLE:
                new = getattr(e, name)
                if new is not None and new != getattr(f, name):
                    changes[name] = new
            if not changes:
                continue
            for name, new in changes.items():
                old = getattr(f, name)
                overrides.append(Override(
                    factor_id=f.factor_id, field=name,
                    old=old.value if isinstance(old, ControlStrength) else old,
                    new=new.value if isinstance(new, ControlStrength) else new,
                    reason=e.reason, by=reviewer, at=at))
            f = f.model_copy(update={**changes, "source": FactorSource.ANALYST})
            inh, res = rules.rate(f.likelihood, f.impact, f.control)
            factors[e.factor_id] = QualitativeFactor.model_validate(
                {**f.model_dump(), "inherent": inh, "residual": res})
        ordered = [factors[f.factor_id] for f in assessment.factors]
        return QualitativeAssessment(
            question=assessment.question, label=assessment.label, factors=ordered,
            overall=rules.overall_rating([f.residual for f in ordered]), overrides=overrides,
            method_note=assessment.method_note,
        )
