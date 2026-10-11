"""Stress-test shock lookup: sector, then asset class, then no shock."""

import numpy as np
import pytest

from models.stress import run_stress
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, StressScenario


def _pos(ticker, asset_class=AssetClass.EQUITY, qty=100.0, price=100.0, sector=None):
    kwargs = dict(
        ticker=ticker,
        asset_class=asset_class,
        quantity=qty,
        cost_price=price,
        currency="USD",
        current_price=price,
        returns_252d=np.random.default_rng(1).normal(0, 0.01, 252).tolist(),
        implied_vol=0.25,
        risk_free_rate=0.04,
        esg_score=60.0,
        carbon_intensity=50.0,
    )
    if sector:
        kwargs["sector"] = sector
    return EnrichedPosition(**kwargs)


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


def _pnl(result):
    return {p.ticker: p.pnl_impact for p in result.positions}


def test_unlisted_asset_classes_are_not_shocked():
    pf = _pf(
        _pos("TECH", sector="Technology"),
        _pos("CASH", AssetClass.CASH, qty=10_000.0, price=1.0),
        _pos("BND", AssetClass.FIXED_INCOME),
    )
    res = run_stress(pf, StressScenario.CUSTOM, {"Technology": -0.20})
    pnl = _pnl(res)
    assert pnl["TECH"] == pytest.approx(-2_000.0)
    assert pnl["CASH"] == 0.0  # used to lose 10%
    assert pnl["BND"] == 0.0  # used to lose 10%


def test_equity_only_custom_shock_does_not_leak_into_bonds():
    pf = _pf(_pos("EQ"), _pos("BND", AssetClass.FIXED_INCOME))
    pnl = _pnl(run_stress(pf, StressScenario.CUSTOM, {"Equity": -0.30}))
    assert pnl["EQ"] == pytest.approx(-3_000.0)
    assert pnl["BND"] == 0.0  # used to lose 30%


def test_sector_shock_takes_precedence_over_asset_class():
    pf = _pf(_pos("BANK", sector="Financials"), _pos("OTHER", sector="Health Care"))
    pnl = _pnl(run_stress(pf, StressScenario.CUSTOM, {"Equity": -0.10, "Financials": -0.50}))
    assert pnl["BANK"] == pytest.approx(-5_000.0)
    assert pnl["OTHER"] == pytest.approx(-1_000.0)


def test_named_scenarios_are_unchanged_because_they_define_every_asset_class():
    pf = _pf(
        _pos("EQ"),
        _pos("BND", AssetClass.FIXED_INCOME),
        _pos("OIL", AssetClass.COMMODITY),
        _pos("CASH", AssetClass.CASH, qty=1_000.0, price=1.0),
    )
    pnl = _pnl(run_stress(pf, StressScenario.CREDIT_2008))
    assert pnl["EQ"] == pytest.approx(-3_500.0)
    assert pnl["BND"] == pytest.approx(-500.0)
    assert pnl["OIL"] == pytest.approx(-2_000.0)
    assert pnl["CASH"] == 0.0


@pytest.mark.parametrize(
    "bad",
    [{"Equity": -1.5}, {"Equity": float("nan")}, {"Equity": float("inf")}, {"Equity": "oops"}],
)
def test_invalid_custom_shocks_are_rejected(bad):
    with pytest.raises(ValueError):
        run_stress(_pf(_pos("EQ")), StressScenario.CUSTOM, bad)


def test_total_loss_and_large_gains_are_valid():
    pnl = _pnl(run_stress(_pf(_pos("EQ"), _pos("S", qty=-100.0)), StressScenario.CUSTOM, {"Equity": -1.0}))
    assert pnl["EQ"] == pytest.approx(-10_000.0)
    assert pnl["S"] == pytest.approx(10_000.0)
    assert run_stress(_pf(_pos("EQ")), StressScenario.CUSTOM, {"Equity": 2.5}).portfolio_pnl == pytest.approx(25_000.0)


def test_custom_scenario_still_requires_shocks():
    with pytest.raises(ValueError):
        run_stress(_pf(_pos("EQ")), StressScenario.CUSTOM, {})
