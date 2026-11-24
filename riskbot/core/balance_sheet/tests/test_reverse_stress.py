"""q2.reverse_stress: breakeven property, consistency with the resilience engine, edge cases."""

from __future__ import annotations

import pytest

from riskbot.contract import conformance
from riskbot.core.balance_sheet import engine
from riskbot.core.balance_sheet.engine import Scenario, evaluate
from riskbot.core.balance_sheet.resilience import ResilienceModel
from riskbot.core.balance_sheet.reverse_stress import (
    ReverseStressModel,
    bisect_breakeven,
    outflow_scenario,
    rate_scenario,
)

from .conftest import tiny_bank

MODEL = ReverseStressModel()


@pytest.mark.parametrize("target", ["capital", "liquidity"])
@pytest.mark.parametrize("htm", ["at_cost", "mark_to_market"])
def test_outflow_breakeven_breaches_at_xstar_not_below(bank, target, htm):
    p = {"target": target, "rate_shock_bp": 200, "htm_treatment": htm, "tolerance": 0.001}
    out = MODEL.run(bank, p, 0)
    assert conformance.check_output(MODEL.spec, out) == []
    assert out.labels["outflow_found"] == "yes"
    x = out.metrics["breakeven_deposit_outflow"].value
    eff = out.params
    at = evaluate(bank, outflow_scenario(eff, x))
    assert engine.is_breach(at, target)
    if x > 0:
        below = evaluate(bank, outflow_scenario(eff, x - eff["tolerance"]))
        assert not engine.is_breach(below, target)


def test_rate_breakeven_breaches_at_star_not_below(bank):
    p = {"target": "capital", "tolerance": 0.0005}
    out = MODEL.run(bank, p, 0)
    assert out.labels["rate_found"] == "yes"
    bp = out.metrics["breakeven_rate_shock_bp"].value
    assert 0 < bp < 1000
    assert evaluate(bank, rate_scenario(out.params, bp)).capital_breach
    assert not evaluate(bank, rate_scenario(out.params, bp - 0.5)).capital_breach


def test_rate_breakeven_consistent_with_resilience_model(bank):
    """Integer shocks just around the breakeven flip the q2.resilience verdict (slow run, base, defaults)."""
    bp = MODEL.run(bank, {"target": "capital", "tolerance": 0.0001}, 0).metrics["breakeven_rate_shock_bp"].value
    res = ResilienceModel()
    lo, hi = int(bp) - 1, int(bp) + 1
    assert res.run(bank, {"rate_shock_bp": lo, "run_speed": "slow"}, 0).labels["binding_constraint"] in ("none", "liquidity")
    assert res.run(bank, {"rate_shock_bp": hi, "run_speed": "slow"}, 0).labels["binding_constraint"] in ("capital", "both")


def test_mark_to_market_breaks_earlier(bank):
    a = MODEL.run(bank, {"htm_treatment": "at_cost"}, 0).metrics["breakeven_rate_shock_bp"].value
    b = MODEL.run(bank, {"htm_treatment": "mark_to_market"}, 0).metrics
    assert "breakeven_rate_shock_bp" not in b or b["breakeven_rate_shock_bp"].value < a


def test_no_breach_omits_metric_and_labels_no(tiny):
    rich = tiny_bank(cet1_capital=5_000, deposits=[], wholesale_funding=[])
    out = MODEL.run(rich, {"target": "capital"}, 0)
    assert conformance.check_output(MODEL.spec, out) == []
    assert out.metrics == {} and out.labels == {"outflow_found": "no", "rate_found": "no"}
    steps = {s.id: s for s in out.traces[0].steps}
    assert steps["breakeven_deposit_outflow"].value is None


def test_breach_at_lower_end_reports_zero(tiny):
    weak = tiny_bank(cet1_capital=1.0)
    out = MODEL.run(weak, {"target": "capital"}, 0)
    assert out.metrics["breakeven_deposit_outflow"].value == 0.0
    assert out.metrics["breakeven_rate_shock_bp"].value == 0.0


class _Fake:
    def __init__(self, v):
        self.capital_ratio_after = v
        self.capital_breach = v < 0.07


def test_bisection_recovers_known_threshold():
    """Linear capital ratio 0.12 - 0.1 x crosses 0.07 at x = 0.5."""
    s = bisect_breakeven(lambda x: _Fake(0.12 - 0.1 * x), "capital", 0.0, 1.0, 1e-6)
    assert s.found and s.monotone
    assert s.value == pytest.approx(0.5, abs=1e-6) and s.value >= 0.5
    assert len(s.iterations) == 17  # bracket 0.1 halved to <= 1e-6


def test_monotonicity_violation_is_flagged_and_smallest_grid_breach_used():
    def fn(x):  # breach only on (0.25, 0.45): non-monotone
        return _Fake(0.05 if 0.25 < x < 0.45 else 0.10)

    s = bisect_breakeven(fn, "capital", 0.0, 1.0, 1e-4)
    assert not s.monotone and s.found and s.value == pytest.approx(0.25, abs=1e-4)


def test_trace_shows_grid_and_iterations(bank):
    out = MODEL.run(bank, {"target": "liquidity"}, 0)
    steps = {s.id: s for s in out.traces[0].steps}
    assert len(steps["deposit_outflow_grid"].table) == 11
    assert steps["deposit_outflow_bisection"].table
    assert out.labels["rate_found"] in ("yes", "no")
    if out.labels["rate_found"] == "no":
        assert "breakeven_rate_shock_bp" not in out.metrics


def test_reverse_stress_uses_same_engine_as_resilience(bank):
    """At x = slow-run equivalent the engine is the one q2.resilience uses: same capital for same scenario."""
    r1 = evaluate(bank, rate_scenario({"htm_treatment": "at_cost"}, 200.0))
    r2 = ResilienceModel().run(bank, {"rate_shock_bp": 200, "run_speed": "slow"}, 0)
    assert r1.capital_ratio_after == pytest.approx(r2.metrics["capital_ratio_after"].value, rel=1e-12)
    assert evaluate(bank, Scenario(run_speed="uniform", uniform_outflow=0.0)).deposit_outflow == 0.0
