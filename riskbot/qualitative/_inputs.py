"""Read-only view over the inputs of one assessment, plus the formatting rules for rationales.

Rules read the dataset, the ``VariationResult`` outputs and the ``Comparison`` only through this
module, so every number a rule uses can be cited as evidence and every number a rationale quotes is a
metric value formatted the way the number verifier expects:

* fractions (``fraction``, ``fraction_of_gross``) -> percent with one decimal, ``0.312 -> "31.2%"``;
* counts and days -> integers, ``780.0 -> "780"``;
* years -> one decimal, ``4.23 -> "4.2"``;
* unitless ratios -> two decimals, ``2.8 -> "2.80"``;
* basis points -> integer followed by ``bp``.

Numbers that do not come from a metric (dataset shares, counts of variations, comparison ratios) are
never printed as digits; rationales describe them in words (``"about a third"``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from riskbot.contract import catalog
from riskbot.contract.types import (
    Comparison,
    DataQualityFinding,
    Evidence,
    ModelOutput,
    QuestionId,
    Unit,
    VariationResult,
)


class MissingInput(Exception):
    """Raised by a rule when an input it needs is absent; the factor becomes ``unassessed``."""

    def __init__(self, what: str, evidence: list[Evidence] | None = None) -> None:
        super().__init__(what)
        self.what = what
        self.evidence = evidence or []


# ---------------------------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------------------------

_PERCENT_UNITS = {Unit.FRACTION, Unit.FRACTION_OF_GROSS}


def fmt_value(value: float, unit: Unit) -> str:
    """Format a metric value exactly as rationales print it (see module docstring)."""
    if unit in _PERCENT_UNITS:
        return f"{value * 100:.1f}%"
    if unit in (Unit.COUNT, Unit.DAYS):
        return f"{round(value):d}"
    if unit == Unit.YEARS:
        return f"{value:.1f}"
    if unit == Unit.BASIS_POINTS:
        return f"{round(value):d} bp"
    if unit == Unit.PROBABILITY:
        return f"{value:.3f}"
    return f"{value:.2f}"


_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]


def count_words(n: int) -> str:
    """Small counts in words (rationales never print non-metric digits)."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else "many"


_SHARE_WORDS = [
    (0.05, "about a twentieth"), (0.10, "about a tenth"), (0.15, "about a seventh"), (0.20, "about a fifth"),
    (0.25, "about a quarter"), (1 / 3, "about a third"), (0.40, "about two fifths"), (0.50, "about half"),
    (0.60, "about three fifths"), (2 / 3, "about two thirds"), (0.75, "about three quarters"),
    (0.85, "most"), (0.95, "nearly all"), (1.0, "all"),
]


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    """'one short position' / 'three short positions' (count in words)."""
    return f"{count_words(n)} {singular if n == 1 else (plural_ or singular + 's')}"


def share_words(x: float) -> str:
    """A share in [0, 1] described in words, e.g. 0.31 -> 'about a third'."""
    if x <= 0:
        return "none"
    if x < 0.03:
        return "a very small share"
    if x >= 0.999:
        return "all"
    return min(_SHARE_WORDS, key=lambda kv: abs(kv[0] - x))[1]


def safe_name(name: str, fallback: str) -> str:
    """Use a dataset label in prose only if it contains no digits (so the verifier sees no stray numbers)."""
    return fallback if re.search(r"\d", name) else name


def metric_name(model_id: str, key: str) -> str:
    """Metric key for prose, or its catalogue description if the key contains digits."""
    if not re.search(r"\d", key):
        return f"'{key}'"
    spec = catalog.MODEL_SPECS.get(model_id)
    desc = next((m.description for m in spec.metrics if m.key == key), key) if spec else key
    return f"'{desc.rstrip('.').lower()}'"


def model_name(model_id: str) -> str:
    """Human name of a catalogue model for prose (model ids contain digits)."""
    spec = catalog.MODEL_SPECS.get(model_id)
    return f"the '{spec.title}' model" if spec else "a required model"


# ---------------------------------------------------------------------------------------------
# Banding
# ---------------------------------------------------------------------------------------------


def band_up(x: float, cuts: Iterable[float]) -> int:
    """Higher is worse: 1 + number of cut points with ``x >= cut`` (four ascending cuts -> 1..5)."""
    return min(5, 1 + sum(1 for c in cuts if x >= c))


def band_down(x: float, cuts: Iterable[float]) -> int:
    """Lower is worse: 1 + number of cut points with ``x < cut`` (four descending cuts -> 1..5)."""
    return min(5, 1 + sum(1 for c in cuts if x < c))


# ---------------------------------------------------------------------------------------------
# Metric references
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricRef:
    """One metric value of one variation, with what is needed to cite and quote it."""

    key: str
    value: float
    unit: Unit
    model_id: str
    variation_id: str
    params: dict[str, Any]
    trace_id: str | None
    trace_step: str | None

    @property
    def text(self) -> str:
        return fmt_value(self.value, self.unit)

    def evidence(self, description: str) -> list[Evidence]:
        ev = [Evidence(kind="metric", ref=self.key, description=f"{description} = {self.text} ({self.model_id}, "
                                                                   f"variation {self.variation_id})")]
        if self.trace_id:
            ref = self.trace_id + (f"/{self.trace_step}" if self.trace_step else "")
            ev.append(Evidence(kind="trace", ref=ref, description=f"Working behind {self.key}."))
        return ev


def label_evidence(result: VariationResult, label: str) -> Evidence:
    assert result.output is not None
    return Evidence(kind="note", ref=f"variation:{result.spec.variation_id}/labels.{label}",
                    description=f"{result.spec.model_id} label {label} = {result.output.labels.get(label)!r}.")


def comparison_evidence(path: str, description: str) -> Evidence:
    return Evidence(kind="note", ref=f"comparison.{path}", description=description)


def finding_evidence(f: DataQualityFinding) -> Evidence:
    return Evidence(kind="finding", ref=f.check, description=f"{f.severity.value}: {f.message}")


def field_evidence(path: str, description: str) -> Evidence:
    return Evidence(kind="dataset_field", ref=path, description=description)


# ---------------------------------------------------------------------------------------------
# Inputs view
# ---------------------------------------------------------------------------------------------


class Inputs:
    """Everything a rule may read. Never mutates the underlying objects."""

    def __init__(self, question: QuestionId, dataset: Any, results: list[VariationResult],
                 comparison: Comparison) -> None:
        self.question = question
        self.dataset = dataset
        self.results = list(results)
        self.comparison = comparison

    # -- results -------------------------------------------------------------------------------

    def successful(self, model_id: str, role: str | None = None) -> list[VariationResult]:
        return [r for r in self.results
                if r.output is not None and r.error is None and r.spec.model_id == model_id
                and (role is None or r.spec.role == role)]

    def grid(self, model_id: str) -> list[VariationResult]:
        return self.successful(model_id, role="grid")

    def first(self, model_id: str, where: Callable[[dict[str, Any]], bool] | None = None) -> VariationResult | None:
        for r in self.successful(model_id):
            if where is None or where(r.spec.params):
                return r
        return None

    def why_missing(self, model_id: str) -> str:
        failed = [r for r in self.results if r.spec.model_id == model_id and r.output is None]
        if failed:
            return f"{model_name(model_id)} failed and produced no output"
        return f"{model_name(model_id)} was not run"

    @staticmethod
    def ref(result: VariationResult, key: str) -> MetricRef | None:
        out: ModelOutput | None = result.output
        if out is None or key not in out.metrics:
            return None
        m = out.metrics[key]
        return MetricRef(key=key, value=m.value, unit=m.unit, model_id=result.spec.model_id,
                         variation_id=result.spec.variation_id, params=dict(result.spec.params),
                         trace_id=m.trace_id, trace_step=m.trace_step)

    def metric(self, model_id: str, key: str, where: Callable[[dict[str, Any]], bool] | None = None) -> MetricRef | None:
        """The metric from the first successful variation of ``model_id`` (matching ``where``) that has it."""
        for r in self.successful(model_id):
            if where is None or where(r.spec.params):
                ref = self.ref(r, key)
                if ref is not None:
                    return ref
        return None

    def require(self, model_id: str, key: str, where: Callable[[dict[str, Any]], bool] | None = None) -> MetricRef:
        ref = self.metric(model_id, key, where)
        if ref is None:
            if self.successful(model_id):
                raise MissingInput(f"metric {metric_name(model_id, key)} is absent from the output of {model_name(model_id)}")
            raise MissingInput(f"metric {metric_name(model_id, key)} ({self.why_missing(model_id)})")
        return ref

    def grid_refs(self, model_id: str, key: str) -> list[MetricRef]:
        return [ref for r in self.grid(model_id) if (ref := self.ref(r, key)) is not None]

    def findings(self) -> list[DataQualityFinding]:
        """Findings of all successful outputs, de-duplicated (same check/field/subject kept once)."""
        seen: set[tuple[str, str, str | None]] = set()
        out = []
        for r in self.results:
            for f in r.output.findings if r.output else []:
                k = (f.check, f.field, f.subject)
                if k not in seen:
                    seen.add(k)
                    out.append(f)
        return out


def lower_median(refs: list[MetricRef]) -> MetricRef:
    """The lower-median element (an actual metric value, so it can be quoted and traced)."""
    s = sorted(refs, key=lambda r: r.value)
    return s[(len(s) - 1) // 2]


def by_param(refs: list[MetricRef], name: str) -> dict[str, list[MetricRef]]:
    groups: dict[str, list[MetricRef]] = {}
    for r in refs:
        if name in r.params:
            groups.setdefault(str(r.params[name]), []).append(r)
    return groups
