"""Greeks: linear positions have only delta; Black-Scholes Greeks match finite differences."""

import math

import numpy as np
import pytest
from scipy.stats import norm

from models.greeks import _black_scholes_greeks, run_greeks
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, GreeksMethod


def _pos(ticker="A", qty=100.0, price=100.0, beta=1.2, asset_class=AssetClass.EQUITY):
    return EnrichedPosition(
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
        beta=beta,
    )


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


# ----------------------------- linear positions -----------------------------


def test_plain_equity_has_only_a_beta_adjusted_delta():
    g = run_greeks(_pf(_pos(qty=100.0, beta=1.2))).positions[0]
    assert g.delta == pytest.approx(120.0)
    assert g.gamma == pytest.approx(0.0, abs=1e-6)
    assert g.vega == 0.0
    assert g.theta == 0.0  # used to be about -$79/day on a $10k position
    assert g.rho == 0.0
    assert g.greeks_method == GreeksMethod.SYNTHETIC_FINITE_DIFFERENCE


def test_short_equity_has_negative_delta_and_still_no_option_greeks():
    g = run_greeks(_pf(_pos(qty=-50.0, beta=1.0))).positions[0]
    assert g.delta == pytest.approx(-50.0)
    assert (g.vega, g.theta, g.rho) == (0.0, 0.0, 0.0)


def test_missing_beta_defaults_to_one():
    pos = _pos(qty=10.0)
    pos.beta = None
    assert run_greeks(_pf(pos)).positions[0].delta == pytest.approx(10.0)


def test_cash_has_only_a_rate_sensitivity_proportional_to_its_signed_value():
    long_cash = run_greeks(_pf(_pos("USD", qty=10_000.0, price=1.0, asset_class=AssetClass.CASH))).positions[0]
    borrowed = run_greeks(_pf(_pos("USD", qty=-10_000.0, price=1.0, asset_class=AssetClass.CASH))).positions[0]
    assert (long_cash.delta, long_cash.gamma, long_cash.vega, long_cash.theta) == (0.0, 0.0, 0.0, 0.0)
    assert long_cash.rho == pytest.approx(1.0)
    assert borrowed.rho == pytest.approx(-1.0)


def test_portfolio_greeks_are_sums_of_position_greeks():
    res = run_greeks(_pf(_pos("A", qty=100.0, beta=1.0), _pos("B", qty=-40.0, beta=2.0)))
    assert res.portfolio_delta == pytest.approx(100.0 - 80.0)
    assert res.portfolio_theta == 0.0
    assert res.portfolio_vega == 0.0


# ----------------------------- Black-Scholes -----------------------------


def _call_price(s, k, t, r, sigma):
    d1 = (math.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return s * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)


def test_black_scholes_call_matches_published_values():
    # S = K = 100, T = 1, r = 5%, sigma = 20%  (textbook example: call price 10.4506)
    g = _black_scholes_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "c")
    assert _call_price(100.0, 100.0, 1.0, 0.05, 0.20) == pytest.approx(10.4506, abs=1e-4)
    assert g["delta"] == pytest.approx(0.6368, abs=1e-4)
    assert g["gamma"] == pytest.approx(0.018762, abs=1e-6)
    assert g["vega"] == pytest.approx(0.37524, abs=1e-5)  # per 1 volatility point
    assert g["rho"] == pytest.approx(0.53233, abs=1e-5)  # per 1 percentage point of rate
    # per calendar day: -(3.7524 + 2.6616) / 365, i.e. -(S*phi(d1)*sigma/2 + r*K*exp(-rT)*N(d2)) / 365
    assert g["theta"] == pytest.approx(-0.017573, abs=1e-6)


def test_black_scholes_greeks_match_finite_differences_of_the_price():
    s, k, t, r, sigma = 105.0, 100.0, 0.75, 0.03, 0.27
    g = _black_scholes_greeks(s, k, t, r, sigma, "c")

    h = 1e-3 * s
    delta = (_call_price(s + h, k, t, r, sigma) - _call_price(s - h, k, t, r, sigma)) / (2 * h)
    gamma = (_call_price(s + h, k, t, r, sigma) - 2 * _call_price(s, k, t, r, sigma) + _call_price(s - h, k, t, r, sigma)) / h**2
    vega = (_call_price(s, k, t, r, sigma + 1e-4) - _call_price(s, k, t, r, sigma - 1e-4)) / 2e-4 * 0.01
    rho = (_call_price(s, k, t, r + 1e-4, sigma) - _call_price(s, k, t, r - 1e-4, sigma)) / 2e-4 * 0.01
    theta_per_day = (_call_price(s, k, t - 1e-4, r, sigma) - _call_price(s, k, t + 1e-4, r, sigma)) / 2e-4 / 365.0

    assert g["delta"] == pytest.approx(delta, rel=1e-5)
    assert g["gamma"] == pytest.approx(gamma, rel=1e-4)
    assert g["vega"] == pytest.approx(vega, rel=1e-5)
    assert g["rho"] == pytest.approx(rho, rel=1e-5)
    assert g["theta"] == pytest.approx(theta_per_day, rel=1e-4)


def test_black_scholes_put_call_relationships():
    s, k, t, r, sigma = 100.0, 95.0, 0.5, 0.04, 0.3
    c = _black_scholes_greeks(s, k, t, r, sigma, "c")
    p = _black_scholes_greeks(s, k, t, r, sigma, "p")
    assert c["delta"] - p["delta"] == pytest.approx(1.0)
    assert c["gamma"] == pytest.approx(p["gamma"])
    assert c["vega"] == pytest.approx(p["vega"])
    assert c["rho"] - p["rho"] == pytest.approx(k * t * math.exp(-r * t) * 0.01)


def test_black_scholes_degenerate_inputs_return_zeros():
    assert set(_black_scholes_greeks(100.0, 100.0, 0.0, 0.05, 0.2, "c").values()) == {0.0}
    assert set(_black_scholes_greeks(100.0, 100.0, 1.0, 0.05, 0.0, "c").values()) == {0.0}
