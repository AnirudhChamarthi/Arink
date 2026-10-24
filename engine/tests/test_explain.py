"""Traces must reproduce the production models exactly and be reproducible."""

import json

import numpy as np
import pytest

from models.explain import explain_parametric_var, explain_stress
from models.portfolio_utils import weight_vector
from models.stress import run_stress
from models.var import parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, StressScenario


def _pos(ticker, returns, qty=100.0, price=100.0, asset_class=AssetClass.EQUITY, sector=None):
    kw = dict(
        ticker=ticker, asset_class=asset_class, quantity=qty, cost_price=price, currency="USD",
        current_price=price, returns_252d=list(returns), implied_vol=0.25, risk_free_rate=0.04,
        esg_score=60.0, carbon_intensity=50.0,
    )
    if sector:
        kw["sector"] = sector
    return EnrichedPosition(**kw)


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


def _book():
    rng = np.random.default_rng(5)
    a = rng.normal(0, 0.01, 252)
    b = 0.4 * a + rng.normal(0, 0.012, 252)
    return _pf(_pos("A", a), _pos("B", b, qty=-60.0), _pos("C", rng.normal(0, 0.02, 120), qty=30.0))


@pytest.mark.parametrize("confidence,horizon", [(0.95, 1), (0.99, 1), (0.99, 10)])
def test_parametric_trace_matches_the_production_model(confidence, horizon):
    pf = _book()
    trace = explain_parametric_var(pf, confidence, horizon)
    prod = parametric_var(pf, confidence, horizon)
    assert trace.result["var"] == pytest.approx(prod.var, rel=1e-12)
    assert trace.result["cvar"] == pytest.approx(prod.cvar, rel=1e-12)
    shares = {r["ticker"]: r["share"] for r in trace.step("contributions").table}
    for c in prod.contributions:
        assert shares[c.ticker.upper()] == pytest.approx(c.pct_of_total, rel=1e-9)


def test_weights_step_matches_weight_vector():
    pf = _book()
    _, w = weight_vector(pf)
    table = explain_parametric_var(pf, 0.99, 1).step("weights").table
    assert [r["weight"] for r in table] == pytest.approx(list(w))


def test_trace_is_deterministic_and_changes_with_inputs():
    pf = _book()
    t1, t2 = explain_parametric_var(pf, 0.99, 1), explain_parametric_var(pf, 0.99, 1)
    assert t1.trace_id == t2.trace_id and t1.input_hash == t2.input_hash
    assert explain_parametric_var(pf, 0.95, 1).trace_id != t1.trace_id


def test_trace_serialises_to_json_and_markdown():
    t = explain_parametric_var(_book(), 0.99, 10)
    json.dumps(t.to_dict())
    md = t.to_markdown()
    assert t.trace_id in md and r"\Phi^{-1}" in md and "## Assumptions" in md


def test_var_amount_is_var_times_gross():
    t = explain_parametric_var(_book(), 0.99, 1)
    gross = t.step("weights").value
    assert t.result["var_amount"] == pytest.approx(t.result["var"] * gross)


def test_empty_portfolio_returns_a_zero_trace_with_a_warning():
    t = explain_parametric_var(_pf(), 0.99, 1)
    assert t.result["var"] == 0.0 and t.warnings


def test_single_observation_is_rejected():
    with pytest.raises(ValueError):
        explain_parametric_var(_pf(_pos("A", [0.01])), 0.99, 1)


def test_stress_trace_matches_the_production_model_and_names_the_shock_source():
    pf = _pf(
        _pos("BANK", [0.0] * 5, sector="Financials"),
        _pos("EQ", [0.0] * 5),
        _pos("BND", [0.0] * 5, asset_class=AssetClass.FIXED_INCOME),
        _pos("SHORT", [0.0] * 5, qty=-50.0),
    )
    shocks = {"Equity": -0.10, "Financials": -0.50}
    trace = explain_stress(pf, StressScenario.CUSTOM, shocks)
    prod = run_stress(pf, StressScenario.CUSTOM, shocks)
    assert trace.result["portfolio_pnl"] == pytest.approx(prod.portfolio_pnl)
    assert trace.result["portfolio_pct"] == pytest.approx(prod.portfolio_pct)
    src = {r["ticker"]: r["shock_source"] for r in trace.step("position_pnl").table}
    assert src == {"BANK": "sector", "EQ": "asset class", "BND": "none", "SHORT": "asset class"}


def test_named_scenario_trace_matches_production():
    pf = _book()
    trace = explain_stress(pf, StressScenario.CREDIT_2008)
    assert trace.result["portfolio_pnl"] == pytest.approx(run_stress(pf, StressScenario.CREDIT_2008).portfolio_pnl)


def test_invalid_shocks_are_rejected_in_traces_too():
    with pytest.raises(ValueError):
        explain_stress(_book(), StressScenario.CUSTOM, {"Equity": -2.0})
