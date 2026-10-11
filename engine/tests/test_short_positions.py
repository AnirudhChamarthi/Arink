"""Short positions (negative quantity) must carry their sign through VaR, stress and weights."""

import numpy as np
import pytest

from models.portfolio_utils import (
    gross_exposure,
    position_market_value,
    position_signed_value,
    position_weights,
    weight_vector,
)
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import historical_var, montecarlo_var, parametric_var
from nlp.executor import _position_weights
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, StressScenario


def _pos(ticker, qty, returns=None, price=100.0, asset_class=AssetClass.EQUITY, sector=None, ci=50.0):
    if returns is None:
        returns = np.random.default_rng(abs(hash(ticker)) % 2**32).normal(0, 0.01, 252)
    kwargs = dict(
        ticker=ticker,
        asset_class=asset_class,
        quantity=qty,
        cost_price=price,
        currency="USD",
        current_price=price,
        returns_252d=np.asarray(returns, dtype=float).tolist(),
        implied_vol=0.25,
        risk_free_rate=0.04,
        esg_score=60.0,
        carbon_intensity=ci,
    )
    if sector:
        kwargs["sector"] = sector
    return EnrichedPosition(**kwargs)


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


# ----------------------------- exposure helpers -----------------------------


def test_signed_value_keeps_the_sign_but_long_book_value_clips_shorts():
    short = _pos("S", -100.0)
    assert position_signed_value(short) == pytest.approx(-10_000.0)
    assert position_market_value(short) == 0.0
    cash = _pos("USD", 5_000.0, returns=np.zeros(252), price=1.0, asset_class=AssetClass.CASH)
    assert position_signed_value(cash) == 5_000.0


def test_gross_exposure_is_sum_of_absolute_values():
    assert gross_exposure(_pf(_pos("L", 100.0), _pos("S", -50.0))) == pytest.approx(15_000.0)


def test_weights_are_signed_and_relative_to_gross_exposure():
    tickers, w = weight_vector(_pf(_pos("L", 100.0), _pos("S", -50.0)))
    assert tickers == ["L", "S"]
    np.testing.assert_allclose(w, [10_000 / 15_000, -5_000 / 15_000])


def test_long_only_weights_are_unchanged_and_sum_to_one():
    _, w = weight_vector(_pf(_pos("A", 100.0), _pos("B", 300.0)))
    np.testing.assert_allclose(w, [0.25, 0.75])
    assert w.sum() == pytest.approx(1.0)


# ----------------------------- VaR -----------------------------


@pytest.mark.parametrize("method", [parametric_var, historical_var, montecarlo_var])
def test_a_perfectly_hedged_book_has_zero_var(method):
    r = np.random.default_rng(2).normal(0, 0.01, 252)
    hedged = _pf(_pos("LONG", 100.0, returns=r), _pos("HEDGE", -100.0, returns=r))
    # Monte Carlo samples from a singular covariance matrix, which leaves ~1e-10 of numerical
    # noise; an unhedged VaR here would be around 2e-2.
    assert method(hedged, 0.99, 1).var == pytest.approx(0.0, abs=1e-8)


def test_short_leg_offsets_a_correlated_long_leg_in_parametric_var():
    rng = np.random.default_rng(3)
    a = rng.normal(0, 0.01, 252)
    b = 0.8 * a + rng.normal(0, 0.006, 252)
    long_only = parametric_var(_pf(_pos("A", 100.0, returns=a)), 0.99, 1).var
    hedged = parametric_var(_pf(_pos("A", 100.0, returns=a), _pos("B", -50.0, returns=b)), 0.99, 1).var
    assert hedged < long_only


def test_short_position_loses_when_the_asset_rallies():
    # Historical VaR of a pure short is the upper tail of the asset's returns.
    r = np.random.default_rng(4).normal(0, 0.01, 252)
    short_var = historical_var(_pf(_pos("S", -100.0, returns=r)), 0.99, 1).var
    assert short_var == pytest.approx(float(np.quantile(r, 0.99)), rel=1e-9)


def test_hedge_has_negative_component_contribution_and_shares_sum_to_one():
    rng = np.random.default_rng(5)
    a = rng.normal(0, 0.01, 252)
    b = 0.8 * a + rng.normal(0, 0.006, 252)
    res = parametric_var(_pf(_pos("A", 100.0, returns=a), _pos("B", -50.0, returns=b)), 0.99, 1)
    by_ticker = {c.ticker: c for c in res.contributions}
    assert by_ticker["B"].pct_of_total < 0
    assert sum(c.pct_of_total for c in res.contributions) == pytest.approx(1.0)


# ----------------------------- stress -----------------------------


def test_short_gains_in_a_crash_scenario():
    res = run_stress(_pf(_pos("S", -100.0)), StressScenario.CREDIT_2008)
    assert res.portfolio_pnl == pytest.approx(3_500.0)  # Equity shock is -35%
    assert res.portfolio_pct == pytest.approx(0.35)


def test_long_short_stress_pnl_and_gross_normalisation():
    pf = _pf(_pos("L", 100.0), _pos("S", -50.0))
    res = run_stress(pf, StressScenario.CREDIT_2008)
    assert res.portfolio_pnl == pytest.approx(-3_500.0 + 1_750.0)
    assert res.portfolio_pct == pytest.approx(-1_750.0 / 15_000.0)


def test_long_only_stress_is_unchanged():
    res = run_stress(_pf(_pos("A", 100.0)), StressScenario.CREDIT_2008)
    assert res.portfolio_pnl == pytest.approx(-3_500.0)
    assert res.portfolio_pct == pytest.approx(-0.35)


# ----------------------------- concentration and ESG -----------------------------


def test_concentration_counts_shorts_by_absolute_exposure():
    rows = _position_weights(_pf(_pos("L", 100.0), _pos("S", -300.0)))
    weights = {t: w for t, w, _ in rows}
    assert weights["S"] == pytest.approx(0.75)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_sustainability_metrics_describe_the_long_book_only():
    pf = _pf(
        _pos("CLEAN", 100.0, ci=10.0, sector="Technology"),
        _pos("DIRTY", -100.0, ci=900.0, sector="Energy"),
    )
    res = run_sustainability(pf)
    assert [w for _, w in position_weights(pf)] == [1.0, 0.0]
    assert res.carbon_intensity_weighted == pytest.approx(10.0)
    assert res.stranded_asset_exposure_pct == pytest.approx(0.0)
