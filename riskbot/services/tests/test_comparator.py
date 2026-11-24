"""Comparator tests on hand-built results."""

import statistics

import pytest

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.types import ExtraRun, GridSpec, QuestionId, QuestionPlan, Unit

from .helpers import make_error, make_result

Q1, Q2 = QuestionId.Q1, QuestionId.Q2

Q2_PLAN = QuestionPlan(
    question=Q2,
    grid=GridSpec(model_id="q2.resilience", dimensions={"rate_shock_bp": [100, 300], "run_speed": ["slow", "fast"]}),
    extras=[ExtraRun(model_id="q2.reverse_stress", params={"target": "capital"}),
            ExtraRun(model_id="q2.reverse_stress", params={"target": "liquidity"})],
)


def _q2_results():
    rows = [  # (shock, speed, capital_ratio_after, credit_loss, verdict)
        (100, "slow", 0.10, 50.0, "pass"),
        (100, "fast", 0.09, 60.0, "pass"),
        (300, "slow", 0.08, 70.0, "pass"),
        (300, "fast", 0.05, 90.0, "fail"),
    ]
    res = [make_result("q2.resilience", {"rate_shock_bp": s, "run_speed": sp},
                       {"capital_ratio_after": c, "credit_loss": cl},
                       {"verdict": v, "binding_constraint": "none" if v == "pass" else "capital"})
           for s, sp, c, cl, v in rows]
    res.append(make_result("q2.reverse_stress", {"target": "capital"}, {"breakeven_deposit_outflow": 0.23},
                           {"outflow_found": "yes", "rate_found": "no"}, role="extra"))
    res.append(make_error("q2.reverse_stress", {"target": "liquidity"}, role="extra"))
    res.append(make_error("q2.resilience", {"rate_shock_bp": 200}))
    return res


@pytest.fixture
def comp():
    return services.comparator().compare(Q2_PLAN, _q2_results())


def test_ranges(comp):
    r = comp.metric_ranges["capital_ratio_after"]
    assert (r.min, r.max, r.n, r.unit) == (0.05, 0.10, 4, Unit.FRACTION)
    assert r.median == pytest.approx(statistics.median([0.10, 0.09, 0.08, 0.05]))
    assert list(comp.metric_ranges) == ["credit_loss", "capital_ratio_after"]  # catalogue order
    assert "breakeven_deposit_outflow" not in comp.metric_ranges  # extras excluded


def test_sensitivity(comp):
    rows = {(s.dimension, s.metric): s for s in comp.sensitivity}
    assert set(rows) == {(d, m) for d in ("rate_shock_bp", "run_speed") for m in ("credit_loss", "capital_ratio_after")}
    s = rows[("rate_shock_bp", "credit_loss")]
    assert s.medians == {"100": 55.0, "300": 80.0}
    assert s.effect == 25.0
    assert list(rows[("run_speed", "capital_ratio_after")].medians) == ["slow", "fast"]
    assert [s.dimension for s in comp.sensitivity] == ["rate_shock_bp"] * 2 + ["run_speed"] * 2


def test_flips(comp):
    got = [(f.dimension, f.from_value, f.to_value, f.outcome_from, f.outcome_to) for f in comp.flips]
    assert got == [("rate_shock_bp", "100", "300", "pass", "fail"), ("run_speed", "slow", "fast", "pass", "fail")]
    assert all(f.label == "verdict" for f in comp.flips)
    assert "run_speed=fast" in comp.flips[0].description
    assert "rate_shock_bp=300" in comp.flips[1].description


def test_break_evens(comp):
    found = [b for b in comp.break_evens if b.found]
    missing = [b for b in comp.break_evens if not b.found]
    assert [(b.name, b.value, b.unit) for b in found] == [("breakeven_deposit_outflow", 0.23, Unit.FRACTION)]
    assert found[0].trace_id and found[0].trace_id.startswith("q2.reverse_stress-")
    assert "target=capital" in found[0].description
    assert [(b.name, b.value, b.unit) for b in missing] == [("breakeven_rate_shock_bp", None, Unit.BASIS_POINTS)]
    assert "target=capital" in missing[0].description
    assert all("liquidity" not in b.description for b in comp.break_evens)  # failed extra: no claims


def test_label_counts(comp):
    assert comp.label_counts["verdict"] == {"pass": 3, "fail": 1}
    assert comp.label_counts["binding_constraint"] == {"none": 3, "capital": 1, "liquidity": 0, "both": 0}


def test_no_method_param_no_spread(comp):
    assert comp.method_spread == {}


def test_method_spread_positive_medians_only():
    plan = QuestionPlan(question=Q1, grid=GridSpec(model_id="q1.var", dimensions={"method": ["normal", "historical", "evt"]}))
    res = [
        make_result("q1.var", {"method": "normal", "window_days": 250}, {"var": 0.02}),
        make_result("q1.var", {"method": "normal", "window_days": 750}, {"var": 0.04}),
        make_result("q1.var", {"method": "historical"}, {"var": 0.05}),
        make_result("q1.var", {"method": "evt"}, {"var": -0.01}),
    ]
    comp = services.comparator().compare(plan, res)
    assert comp.method_spread["var"] == pytest.approx(0.05 / 0.03)
    only_one = services.comparator().compare(plan, res[:2])
    assert only_one.method_spread == {}


def test_dimension_dropped_by_applies_when_is_skipped():
    plan = QuestionPlan(question=Q1, grid=GridSpec(model_id="q1.var", dimensions={
        "method": ["normal", "historical"], "covariance": ["sample", "ledoit_wolf"]}))
    res = [make_result("q1.var", {"method": "normal", "covariance": "sample"}, {"var": 0.02},
                       {"backtest_verdict": "pass"}),
           make_result("q1.var", {"method": "normal", "covariance": "ledoit_wolf"}, {"var": 0.03},
                       {"backtest_verdict": "fail"}),
           make_result("q1.var", {"method": "historical"}, {"var": 0.05}, {"backtest_verdict": "fail"})]
    comp = services.comparator().compare(plan, res)
    row = next(s for s in comp.sensitivity if s.dimension == "covariance" and s.metric == "var")
    assert row.medians == {"sample": 0.02, "ledoit_wolf": 0.03}
    assert [(f.dimension, f.from_value, f.to_value) for f in comp.flips] == [("covariance", "sample", "ledoit_wolf")]


def test_na_outcomes_are_not_flips():
    plan = QuestionPlan(question=Q1, grid=GridSpec(model_id="q1.var", dimensions={"window_days": [250, 750]}))
    res = [make_result("q1.var", {"window_days": 250}, {"var": 0.02}, {"backtest_verdict": "pass"}),
           make_result("q1.var", {"window_days": 750}, {"var": 0.03}, {"backtest_verdict": "n/a"})]
    assert services.comparator().compare(plan, res).flips == []


def test_flip_cap_deterministic():
    plan = catalog.DEFAULT_PLANS[Q2]
    specs = [s for s in services.planner().expand(plan, 0) if s.role == "grid"]
    res = [make_result("q2.resilience", s.params, {"credit_loss": float(i)},
                       {"verdict": "pass" if bin(i).count("1") % 2 else "fail"}) for i, s in enumerate(specs)]
    a = services.comparator().compare(plan, res).flips
    b = services.comparator().compare(plan, res).flips
    assert len(a) == 50 and a == b
    keys = [(f.dimension, f.description) for f in a]
    assert len(set(keys)) == len(keys)


def test_empty_and_all_failed():
    plan = catalog.DEFAULT_PLANS[Q2]
    for res in ([], [make_error("q2.resilience", {})]):
        comp = services.comparator().compare(plan, res)
        assert comp.question == Q2 and comp.metric_ranges == {} and comp.flips == [] and comp.break_evens == []
        assert comp.sensitivity == [] and comp.label_counts == {} and comp.method_spread == {}
