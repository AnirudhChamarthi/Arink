"""Statistical properties of the existing VaR / expected-shortfall / GARCH code.

Each test compares the implementation with a closed-form or theoretical result, so a failure
points at the maths rather than at an arbitrary expected number.
"""

import math

import numpy as np
import pytest
from scipy import stats

from models.garch import run_garch
from models.var import historical_var, montecarlo_var, parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _position(ticker: str, returns, qty: float = 100.0, price: float = 100.0) -> EnrichedPosition:
    return EnrichedPosition(
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=qty,
        cost_price=price,
        currency="USD",
        current_price=price,
        returns_252d=np.asarray(returns, dtype=float).tolist(),
        implied_vol=0.25,
        risk_free_rate=0.04,
        esg_score=60.0,
        carbon_intensity=50.0,
    )


def _portfolio(*positions: EnrichedPosition) -> EnrichedPortfolio:
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


@pytest.fixture
def returns_a() -> np.ndarray:
    return np.random.default_rng(1).normal(0.0, 0.01, 252)


# ------------------------- parametric VaR / ES -------------------------


@pytest.mark.parametrize("confidence", [0.95, 0.99])
def test_parametric_var_is_z_times_sigma(returns_a, confidence):
    res = parametric_var(_portfolio(_position("A", returns_a)), confidence, 1)
    assert res.var == pytest.approx(stats.norm.ppf(confidence) * np.std(returns_a, ddof=1), rel=1e-9)


def test_parametric_var_scales_with_square_root_of_horizon(returns_a):
    pf = _portfolio(_position("A", returns_a))
    one = parametric_var(pf, 0.99, 1).var
    assert parametric_var(pf, 0.99, 10).var == pytest.approx(one * math.sqrt(10), rel=1e-9)


@pytest.mark.parametrize("confidence", [0.95, 0.975, 0.99])
def test_parametric_cvar_matches_normal_expected_shortfall_formula(returns_a, confidence):
    # Normal ES = sigma * phi(z_c) / (1 - c)
    res = parametric_var(_portfolio(_position("A", returns_a)), confidence, 1)
    sigma = np.std(returns_a, ddof=1)
    z = stats.norm.ppf(confidence)
    assert res.cvar == pytest.approx(sigma * stats.norm.pdf(z) / (1 - confidence), rel=1e-9)


@pytest.mark.parametrize("method", [parametric_var, historical_var, montecarlo_var])
def test_expected_shortfall_is_at_least_var(returns_a, method):
    res = method(_portfolio(_position("A", returns_a)), 0.99, 1)
    assert res.cvar >= res.var


def test_higher_confidence_gives_higher_var(returns_a):
    pf = _portfolio(_position("A", returns_a))
    assert parametric_var(pf, 0.99, 1).var > parametric_var(pf, 0.95, 1).var
    assert historical_var(pf, 0.99, 1).var > historical_var(pf, 0.95, 1).var


def test_parametric_var_is_subadditive_for_imperfectly_correlated_assets():
    # Equal market values -> equal weights, so portfolio VaR must not exceed the average
    # of the stand-alone VaRs (diversification), with strict inequality when correlation < 1.
    rng = np.random.default_rng(2)
    a = rng.normal(0, 0.01, 252)
    b = 0.3 * a + rng.normal(0, 0.012, 252)
    both = parametric_var(_portfolio(_position("A", a), _position("B", b)), 0.99, 1).var
    alone_a = parametric_var(_portfolio(_position("A", a)), 0.99, 1).var
    alone_b = parametric_var(_portfolio(_position("B", b)), 0.99, 1).var
    assert both < 0.5 * alone_a + 0.5 * alone_b


def test_perfectly_correlated_assets_give_no_diversification_benefit():
    a = np.random.default_rng(4).normal(0, 0.01, 252)
    both = parametric_var(_portfolio(_position("A", a), _position("B", 2 * a)), 0.99, 1).var
    alone_a = parametric_var(_portfolio(_position("A", a)), 0.99, 1).var
    alone_b = parametric_var(_portfolio(_position("B", 2 * a)), 0.99, 1).var
    assert both == pytest.approx(0.5 * alone_a + 0.5 * alone_b, rel=1e-9)


# ----------------------------- historical VaR -----------------------------


def test_historical_var_equals_empirical_loss_quantile(returns_a):
    res = historical_var(_portfolio(_position("A", returns_a)), 0.99, 1)
    assert res.var == pytest.approx(float(np.quantile(-returns_a, 0.99)), rel=1e-12)
    tail = (-returns_a)[(-returns_a) >= res.var]
    assert res.cvar == pytest.approx(float(tail.mean()), rel=1e-12)


# ----------------------------- Monte Carlo VaR -----------------------------


def test_montecarlo_var_converges_to_parametric_for_zero_mean_returns():
    r = np.random.default_rng(6).normal(0, 0.01, 252)
    r = r - r.mean()  # remove drift so the two methods target the same quantity
    pf = _portfolio(_position("A", r))
    mc = montecarlo_var(pf, 0.99, 1, n_sims=200_000).var
    assert mc == pytest.approx(parametric_var(pf, 0.99, 1).var, rel=0.03)


@pytest.mark.parametrize("mu", [0.002, 0.0, -0.002])
def test_montecarlo_multiday_var_scales_drift_linearly(mu):
    # Regression test: the drift used to be scaled by sqrt(h) instead of h, overstating
    # multi-day VaR for a positive mean and understating it for a negative one.
    sigma, h = 0.01, 10
    r = np.random.default_rng(8).normal(0, sigma, 252)
    r = (r - r.mean()) / r.std(ddof=1) * sigma + mu  # exact sample mean and std
    pf = _portfolio(_position("A", r))

    z = stats.norm.ppf(0.99)
    theoretical = z * sigma * math.sqrt(h) - h * mu  # VaR of N(h*mu, sigma^2 * h)
    mc = montecarlo_var(pf, 0.99, h, n_sims=200_000).var
    assert mc == pytest.approx(theoretical, rel=0.03)


# --------------------------------- GARCH ---------------------------------


def _simulate_garch(n=252, omega=2e-6, a=0.1, b=0.85, seed=3) -> np.ndarray:
    g = np.random.default_rng(seed)
    x = np.zeros(n)
    h = omega / (1 - a - b)
    for t in range(n):
        x[t] = math.sqrt(h) * g.standard_normal()
        h = omega + a * x[t] ** 2 + b * h
    return x


def test_garch_fit_is_stationary_and_persistent():
    res = run_garch(_portfolio(_position("G", _simulate_garch())), "G")
    # True alpha + beta is 0.95. With one year of data the individual parameters are noisy,
    # but the persistence should be high and the process stationary.
    assert res.omega > 0
    assert res.alpha >= 0 and res.beta_param >= 0
    assert 0.85 < res.alpha + res.beta_param < 1.0
    assert res.arma_order is None  # the real arch fit, not the EWMA fallback


def test_garch_conditional_var_is_normal_quantile_of_next_day_volatility():
    res = run_garch(_portfolio(_position("G", _simulate_garch())), "G")
    assert res.conditional_var_1d == pytest.approx(
        res.vol_forecast_series[0] * stats.norm.ppf(0.99), rel=1e-9
    )
    assert len(res.vol_forecast_series) == 10
    assert all(v > 0 for v in res.vol_forecast_series)


def test_garch_requires_enough_history():
    with pytest.raises(ValueError):
        run_garch(_portfolio(_position("G", np.zeros(20))), "G")
    with pytest.raises(ValueError):
        run_garch(_portfolio(_position("G", _simulate_garch())), "MISSING")
