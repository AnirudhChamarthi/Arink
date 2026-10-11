"""Risk modes: every parameter is checked against the formula it is supposed to change."""

import math
from dataclasses import replace

import numpy as np
import pytest
from scipy import integrate, stats

from models.risk_modes import (
    PROFILES,
    RiskMode,
    RiskProfile,
    VolEstimator,
    es_multiplier,
    ewma_covariance,
    moded_parametric_var,
    profile_covariance,
    run_stress_with_mode,
    run_sustainability_with_mode,
    sample_covariance,
    scaled_shocks,
    stress_correlation,
    var_quantile,
)
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition, StressScenario


def _position(ticker, returns, asset_class=AssetClass.EQUITY, qty=100.0, price=100.0, ci=50.0, sector=None):
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


def _portfolio(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


def _two_asset_returns(vol_path: np.ndarray, seed: int = 21):
    """Two correlated return series (corr about 0.4) sharing a time-varying volatility path."""
    rng = np.random.default_rng(seed)
    n = vol_path.size
    common, ia, ib = rng.standard_normal(n), rng.standard_normal(n), rng.standard_normal(n)
    return vol_path * (0.6 * common + 0.8 * ia), vol_path * (0.6 * common + 0.8 * ib)


RECENT_SPIKE = np.r_[np.full(232, 0.010), np.full(20, 0.022)]  # calm year, volatile last month
RECENT_CALM = np.r_[np.full(232, 0.020), np.full(20, 0.005)]  # volatile year, calm last month


# ----------------------------- profiles -----------------------------


def test_profiles_get_more_conservative_from_optimistic_to_cautious():
    o, n, c = (PROFILES[m] for m in (RiskMode.OPTIMISTIC, RiskMode.NORMAL, RiskMode.CAUTIOUS))
    assert o.confidence < n.confidence < c.confidence
    assert o.corr_stress <= n.corr_stress < c.corr_stress
    assert o.stress_multiplier < n.stress_multiplier < c.stress_multiplier
    assert o.carbon_price < n.carbon_price < c.carbon_price
    assert n.tail_dof is None and o.tail_dof is None and c.tail_dof is not None


@pytest.mark.parametrize(
    "bad",
    [
        dict(confidence=1.0),
        dict(confidence=0.0),
        dict(corr_stress=-0.1),
        dict(corr_stress=1.1),
        dict(tail_dof=2.0),
        dict(stress_multiplier=0.0),
        dict(ewma_lambda=1.0),
        dict(carbon_price=-1.0),
    ],
)
def test_profile_validation(bad):
    with pytest.raises(ValueError):
        replace(PROFILES[RiskMode.NORMAL], **bad)


# ----------------------------- covariance pieces -----------------------------


def test_ewma_covariance_matches_hand_recursion():
    a, b = _two_asset_returns(RECENT_SPIKE)
    R = np.column_stack([a, b])
    lam = 0.94
    expected = np.cov(R, rowvar=False)
    for row in R:
        expected = lam * expected + (1 - lam) * np.outer(row, row)
    np.testing.assert_allclose(ewma_covariance(R, lam), expected, rtol=1e-12)


def test_ewma_reacts_to_recent_spike_more_than_sample():
    a, _ = _two_asset_returns(RECENT_SPIKE)
    R = a.reshape(-1, 1)
    assert ewma_covariance(R)[0, 0] > sample_covariance(R)[0, 0]


def test_stress_correlation_endpoints_and_validity():
    corr = np.array([[1.0, 0.2, -0.3], [0.2, 1.0, 0.5], [-0.3, 0.5, 1.0]])
    np.testing.assert_allclose(stress_correlation(corr, 0.0), corr)
    np.testing.assert_allclose(stress_correlation(corr, 1.0), np.ones((3, 3)))
    mid = stress_correlation(corr, 0.3)
    np.testing.assert_allclose(np.diag(mid), 1.0)
    assert np.linalg.eigvalsh(mid).min() > -1e-12  # still a valid (PSD) correlation matrix
    assert mid[0, 1] == pytest.approx(0.7 * 0.2 + 0.3)


def test_full_correlation_stress_removes_diversification():
    a, b = _two_asset_returns(RECENT_SPIKE)
    pf = _portfolio(_position("A", a), _position("B", b))  # equal market values -> weights 1/2, 1/2
    stressed = replace(PROFILES[RiskMode.NORMAL], corr_stress=1.0)
    res = moded_parametric_var(pf, profile=stressed)

    vols = np.sqrt(np.diag(ewma_covariance(np.column_stack([a, b]))))
    assert res.portfolio_vol_daily == pytest.approx(0.5 * vols[0] + 0.5 * vols[1], rel=1e-9)


def test_min_and_max_estimators_take_the_calmer_and_harsher_of_sample_and_ewma_vol():
    for path, ewma_is_larger in ((RECENT_SPIKE, True), (RECENT_CALM, False)):
        a, b = _two_asset_returns(path)
        R = np.column_stack([a, b])
        s_vol = np.sqrt(np.diag(sample_covariance(R)))
        e_vol = np.sqrt(np.diag(ewma_covariance(R)))
        assert (e_vol > s_vol).all() == ewma_is_larger

        cautious = replace(PROFILES[RiskMode.CAUTIOUS], corr_stress=0.0)
        optimistic = PROFILES[RiskMode.OPTIMISTIC]  # corr_stress is already 0
        got_max = np.sqrt(np.diag(profile_covariance(R, cautious)))
        got_min = np.sqrt(np.diag(profile_covariance(R, optimistic)))
        np.testing.assert_allclose(got_max, np.maximum(s_vol, e_vol), rtol=1e-12)
        np.testing.assert_allclose(got_min, np.minimum(s_vol, e_vol), rtol=1e-12)


# ----------------------------- tail multipliers -----------------------------


def test_student_t_quantile_is_scaled_to_unit_variance():
    nu, c = 5.0, 0.99
    assert var_quantile(c, nu) == pytest.approx(stats.t.ppf(c, nu) * math.sqrt(3 / 5), rel=1e-12)
    assert var_quantile(c, nu) == pytest.approx(2.6065, abs=1e-3)
    assert var_quantile(c, None) == pytest.approx(stats.norm.ppf(c))


def test_student_t_converges_to_normal_as_dof_grows():
    for c in (0.95, 0.99):
        assert var_quantile(c, 1e7) == pytest.approx(var_quantile(c, None), abs=1e-3)
        assert es_multiplier(c, 1e7) == pytest.approx(es_multiplier(c, None), abs=1e-3)


@pytest.mark.parametrize("nu", [4.0, 5.0, 10.0])
@pytest.mark.parametrize("c", [0.95, 0.99])
def test_student_t_expected_shortfall_matches_numerical_integration(nu, c):
    # ES = (1 / (1 - c)) * integral from VaR to infinity of x f(x) dx, for the unit-variance t.
    s = math.sqrt((nu - 2) / nu)
    pdf = lambda x: stats.t.pdf(x / s, nu) / s
    q = var_quantile(c, nu)
    numeric, _ = integrate.quad(lambda x: x * pdf(x), q, np.inf)
    assert es_multiplier(c, nu) == pytest.approx(numeric / (1 - c), rel=1e-6)


def test_fat_tails_make_far_tail_more_severe_but_not_every_quantile():
    # With variance held fixed, a t distribution has a thinner shoulder and a fatter far tail.
    assert var_quantile(0.95, 5.0) < var_quantile(0.95, None)
    assert var_quantile(0.99, 5.0) > var_quantile(0.99, None)
    assert es_multiplier(0.95, 5.0) > es_multiplier(0.95, None)  # ES sees the tail either way


# ----------------------------- moded VaR -----------------------------


def test_sample_estimator_profile_reduces_to_the_existing_parametric_var():
    a, b = _two_asset_returns(RECENT_SPIKE)
    pf = _portfolio(_position("A", a), _position("B", b))
    sample_profile = replace(
        PROFILES[RiskMode.NORMAL], vol_estimator=VolEstimator.SAMPLE, confidence=0.99
    )
    got = moded_parametric_var(pf, profile=sample_profile)
    assert got.var == pytest.approx(parametric_var(pf, 0.99, 1).var, rel=1e-9)
    assert got.es == pytest.approx(parametric_var(pf, 0.99, 1).cvar, rel=1e-9)


def test_normal_mode_equals_z_times_ewma_volatility_for_one_asset():
    a, _ = _two_asset_returns(RECENT_SPIKE)
    var = float(np.var(a, ddof=1))
    for r in a:
        var = 0.94 * var + 0.06 * r * r
    res = moded_parametric_var(_portfolio(_position("A", a)), RiskMode.NORMAL)
    assert res.var == pytest.approx(stats.norm.ppf(0.99) * math.sqrt(var), rel=1e-9)


def test_var_scales_with_square_root_of_horizon_in_every_mode():
    a, b = _two_asset_returns(RECENT_SPIKE)
    pf = _portfolio(_position("A", a), _position("B", b))
    for mode in RiskMode:
        one = moded_parametric_var(pf, mode, horizon_days=1)
        ten = moded_parametric_var(pf, mode, horizon_days=10)
        assert ten.var == pytest.approx(one.var * math.sqrt(10), rel=1e-9)
        assert ten.es == pytest.approx(one.es * math.sqrt(10), rel=1e-9)


@pytest.mark.parametrize("path", [RECENT_SPIKE, RECENT_CALM])
def test_modes_are_ordered_at_a_fixed_confidence(path):
    a, b = _two_asset_returns(path)
    pf = _portfolio(_position("A", a), _position("B", b))
    results = {m: moded_parametric_var(pf, m, confidence=0.99) for m in RiskMode}
    assert results[RiskMode.OPTIMISTIC].var <= results[RiskMode.NORMAL].var <= results[RiskMode.CAUTIOUS].var
    assert results[RiskMode.OPTIMISTIC].es <= results[RiskMode.NORMAL].es <= results[RiskMode.CAUTIOUS].es


def test_calm_recent_period_is_where_cautious_differs_most_from_normal():
    # EWMA forgets an old turbulent period quickly; the cautious max-rule does not.
    a, b = _two_asset_returns(RECENT_CALM)
    pf = _portfolio(_position("A", a), _position("B", b))
    normal = moded_parametric_var(pf, RiskMode.NORMAL, confidence=0.99).portfolio_vol_daily
    cautious = moded_parametric_var(pf, RiskMode.CAUTIOUS, confidence=0.99).portfolio_vol_daily
    assert cautious > 1.5 * normal


def test_each_default_confidence_is_used_unless_overridden():
    a, _ = _two_asset_returns(RECENT_SPIKE)
    pf = _portfolio(_position("A", a))
    assert moded_parametric_var(pf, RiskMode.CAUTIOUS).confidence == 0.995
    assert moded_parametric_var(pf, RiskMode.CAUTIOUS, confidence=0.9).confidence == 0.9


def test_cash_position_and_empty_portfolio_do_not_produce_nan():
    a, _ = _two_asset_returns(RECENT_SPIKE)
    pf = _portfolio(
        _position("A", a),
        _position("CASH", np.zeros(a.size), asset_class=AssetClass.CASH, qty=10_000.0, price=1.0),
    )
    for mode in RiskMode:
        res = moded_parametric_var(pf, mode)
        assert math.isfinite(res.var) and res.var > 0
    empty = moded_parametric_var(_portfolio(), RiskMode.CAUTIOUS)
    assert empty.var == 0.0 and empty.es == 0.0


def test_moded_var_input_validation():
    pf = _portfolio(_position("A", np.random.default_rng(0).normal(0, 0.01, 252)))
    with pytest.raises(ValueError):
        moded_parametric_var(pf, horizon_days=0)
    with pytest.raises(ValueError):
        moded_parametric_var(pf, confidence=1.0)


# ----------------------------- stress severity -----------------------------


def test_scaled_shocks_losses_multiplied_gains_divided_and_floored():
    out = scaled_shocks({"loss": -0.30, "gain": 0.30, "zero": 0.0, "wipeout": -0.80}, 2.0)
    assert out["loss"] == pytest.approx(-0.60)
    assert out["gain"] == pytest.approx(0.15)
    assert out["zero"] == 0.0
    assert out["wipeout"] == -1.0  # cannot lose more than everything
    assert scaled_shocks({"x": -0.2, "y": 0.1}, 1.0) == {"x": -0.2, "y": 0.1}
    with pytest.raises(ValueError):
        scaled_shocks({"x": -0.1}, 0.0)


def test_stress_modes_scale_the_portfolio_loss():
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 252)
    pf = _portfolio(
        _position("EQ", r),
        _position("BND", r, asset_class=AssetClass.FIXED_INCOME),
        _position("CASH", np.zeros(252), asset_class=AssetClass.CASH, qty=5_000.0, price=1.0),
    )
    base = run_stress(pf, StressScenario.CREDIT_2008)
    normal = run_stress_with_mode(pf, StressScenario.CREDIT_2008, RiskMode.NORMAL)
    optimistic = run_stress_with_mode(pf, StressScenario.CREDIT_2008, RiskMode.OPTIMISTIC)
    cautious = run_stress_with_mode(pf, StressScenario.CREDIT_2008, RiskMode.CAUTIOUS)

    assert normal.portfolio_pnl == pytest.approx(base.portfolio_pnl)
    assert normal.scenario == "2008_credit"
    assert cautious.portfolio_pnl < normal.portfolio_pnl < optimistic.portfolio_pnl < 0
    # 2008 shocks: Equity -35% and FixedIncome -5% are both losses, so pnl scales by exactly m.
    assert cautious.portfolio_pnl == pytest.approx(1.5 * base.portfolio_pnl)
    assert optimistic.portfolio_pnl == pytest.approx(0.75 * base.portfolio_pnl)


def test_cautious_mode_does_not_scale_up_offsetting_gains():
    r = np.random.default_rng(4).normal(0, 0.01, 252)
    pf = _portfolio(_position("OIL", r, asset_class=AssetClass.COMMODITY, qty=100.0, price=100.0))
    base = run_stress(pf, StressScenario.OIL_SPIKE_50PCT)  # Commodity +15% (a gain)
    cautious = run_stress_with_mode(pf, StressScenario.OIL_SPIKE_50PCT, RiskMode.CAUTIOUS)
    assert base.portfolio_pnl > 0
    assert cautious.portfolio_pnl == pytest.approx(base.portfolio_pnl / 1.5)


def test_custom_stress_with_mode_requires_shocks():
    pf = _portfolio(_position("A", np.random.default_rng(1).normal(0, 0.01, 252)))
    with pytest.raises(ValueError):
        run_stress_with_mode(pf, StressScenario.CUSTOM, RiskMode.CAUTIOUS)


# ----------------------------- sustainability -----------------------------


def test_carbon_var_scales_linearly_with_the_mode_carbon_price():
    r = np.random.default_rng(5).normal(0, 0.01, 252)
    pf = _portfolio(_position("OILCO", r, ci=400.0, sector="Energy"), _position("TECH", r, ci=20.0, sector="Technology"))
    normal = run_sustainability_with_mode(pf, RiskMode.NORMAL).carbon_var
    assert normal == pytest.approx(run_sustainability(pf).carbon_var)  # normal == existing default
    assert run_sustainability_with_mode(pf, RiskMode.CAUTIOUS).carbon_var == pytest.approx(2.0 * normal)
    assert run_sustainability_with_mode(pf, RiskMode.OPTIMISTIC).carbon_var == pytest.approx(0.5 * normal)
