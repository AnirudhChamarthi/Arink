"""Properties every assessment must have, checked on every hand-built scenario."""

from __future__ import annotations

import inspect

import pytest

from riskbot.contract import rules
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.ports import Assessor
from riskbot.contract.types import (
    Comparison,
    ControlStrength,
    FactorSource,
    QualitativeAssessment,
    QuestionId,
)
from riskbot.qualitative import CONTRACT_FACTOR_IDS, RUBRICS, assessor
from riskbot.qualitative._inputs import fmt_value

from ._builders import NUMBER, resolve_field
from ._scenarios import ALL

SCENARIOS = list(ALL)


def _assess(name):
    s = ALL[name]()
    return s, assessor().assess(s.question, s.dataset, s.results, s.comparison)


def test_assessor_satisfies_port():
    """Structural check against the (non runtime-checkable) Protocol: same methods and parameter names."""
    a = assessor()
    for name in ("assess", "apply_edits"):
        want = list(inspect.signature(getattr(Assessor, name)).parameters)[1:]
        assert list(inspect.signature(getattr(a, name)).parameters) == want


def test_rubrics_have_exactly_the_contract_factor_ids():
    # CONTRACT.md section 8, copied literally so a drift in either place fails.
    section8 = {
        QuestionId.Q1: ["method_spread", "backtest_performance", "history_length", "data_quality", "concentration",
                        "short_exposure", "normality_reliance"],
        QuestionId.Q2: ["uninsured_deposits", "deposit_concentration", "duration_gap", "hedging", "htm_reliance",
                        "wholesale_dependence", "risk_governance", "credit_concentration"],
        QuestionId.Q3: ["emissions_coverage", "estimated_emissions", "scope3_coverage", "stale_data",
                        "controversies", "exclusion_breaches", "high_emitting_concentration", "scenario_dispersion"],
    }
    for q, ids in section8.items():
        assert [fd.factor_id for fd in RUBRICS[q]] == ids
        assert list(CONTRACT_FACTOR_IDS[q]) == ids
        for fd in RUBRICS[q]:
            assert fd.name and fd.description and fd.inputs and fd.control_basis and 1 <= fd.default_impact <= 5


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_factor_present_exactly_once(name):
    s, a = _assess(name)
    ids = [f.factor_id for f in a.factors]
    assert ids == list(CONTRACT_FACTOR_IDS[s.question])
    assert len(set(ids)) == len(ids)
    assert a.label == "judgment" and a.question == s.question and "judgment" in a.method_note.lower()


@pytest.mark.parametrize("name", SCENARIOS)
def test_ratings_consistent_with_rules(name):
    _, a = _assess(name)
    for f in a.factors:
        assert (f.inherent, f.residual) == rules.rate(f.likelihood, f.impact, f.control)
    assert a.overall == rules.overall_rating([f.residual for f in a.factors])


@pytest.mark.parametrize("name", SCENARIOS)
def test_unassessed_factors_are_neutral_placeholders(name):
    _, a = _assess(name)
    for f in a.factors:
        if f.source == FactorSource.UNASSESSED:
            assert (f.likelihood, f.impact, f.control) == (3, 3, ControlStrength.ADEQUATE)
            assert "missing" in f.rationale.lower()
        else:
            assert f.source == FactorSource.RULE
            assert f.evidence


@pytest.mark.parametrize("name", SCENARIOS)
def test_evidence_refs_exist_in_inputs(name):
    s, a = _assess(name)
    metric_keys = {k for r in s.results if r.output for k in r.output.metrics}
    steps = {f"{t.trace_id}/{st.id}" for r in s.results if r.output for t in r.output.traces for st in t.steps}
    checks = {f.check for r in s.results if r.output for f in r.output.findings}
    labels = {(r.spec.variation_id, lab) for r in s.results if r.output for lab in r.output.labels}
    comp = s.comparison.model_dump()
    for f in a.factors:
        for e in f.evidence:
            if e.kind == "metric":
                assert e.ref in metric_keys, (f.factor_id, e.ref)
            elif e.kind == "trace":
                assert e.ref in steps, (f.factor_id, e.ref)
            elif e.kind == "finding":
                assert e.ref in checks, (f.factor_id, e.ref)
            elif e.kind == "dataset_field":
                resolve_field(s.dataset, e.ref)  # raises if the path does not exist
            else:  # note
                if e.ref.startswith("comparison."):
                    head = e.ref.split(".")[1]
                    assert head in comp, (f.factor_id, e.ref)
                    assert comp[head] or head == "flips", (f.factor_id, e.ref)  # "no flips" is evidence too
                    if head in ("method_spread", "label_counts", "metric_ranges"):
                        assert e.ref.split(".")[2] in comp[head]
                elif e.ref.startswith("variation:"):
                    vid, lab = e.ref[len("variation:"):].split("/labels.")
                    assert (vid, lab) in labels, (f.factor_id, e.ref)
                else:
                    assert e.ref == f"missing:{f.factor_id}" and f.source == FactorSource.UNASSESSED


@pytest.mark.parametrize("name", SCENARIOS)
def test_rationale_numbers_are_copied_metric_values(name):
    """Every number printed in a rationale is a metric value as formatted, or a 1-5 integer."""
    s, a = _assess(name)
    allowed = {"1", "2", "3", "4", "5"}
    for r in s.results:
        for m in r.output.metrics.values() if r.output else []:
            allowed |= set(NUMBER.findall(fmt_value(m.value, m.unit)))
    for f in a.factors:
        for tok in NUMBER.findall(f.rationale):
            assert tok in allowed, (f.factor_id, tok, f.rationale)


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_json_round_trip_and_inputs_untouched(name):
    s = ALL[name]()
    before = ([r.model_dump_json() for r in s.results], s.comparison.model_dump_json(), s.dataset.model_dump_json())
    a1 = assessor().assess(s.question, s.dataset, s.results, s.comparison)
    a2 = assessor().assess(s.question, s.dataset, s.results, s.comparison)
    assert a1 == a2
    assert QualitativeAssessment.model_validate_json(a1.model_dump_json()) == a1
    after = ([r.model_dump_json() for r in s.results], s.comparison.model_dump_json(), s.dataset.model_dump_json())
    assert before == after


@pytest.mark.parametrize("name", ["q1_missing", "q2_missing", "q3_missing"])
def test_missing_model_outputs_give_unassessed(name):
    _, a = _assess(name)
    unassessed = [f for f in a.factors if f.source == FactorSource.UNASSESSED]
    assert len(unassessed) >= 4
    assert all("failed" in f.rationale or "missing" in f.rationale.lower() for f in unassessed)


def test_wrong_dataset_or_comparison_rejected():
    a = assessor()
    with pytest.raises(ValidationFailed):
        a.assess(QuestionId.Q1, fake_dataset(QuestionId.Q2), [], Comparison(question=QuestionId.Q1, metric_ranges={}))
    with pytest.raises(ValidationFailed):
        a.assess(QuestionId.Q1, fake_dataset(QuestionId.Q1), [], Comparison(question=QuestionId.Q3, metric_ranges={}))


@pytest.mark.parametrize("q", list(QuestionId))
def test_empty_results_still_complete(q):
    a = assessor().assess(q, fake_dataset(q), [], Comparison(question=q, metric_ranges={}))
    assert [f.factor_id for f in a.factors] == list(CONTRACT_FACTOR_IDS[q])
