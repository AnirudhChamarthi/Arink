"""Backtesting statistics: checked against hand-computed textbook values and simulated data."""

import math

import numpy as np
import pytest
from scipy import stats

from models.backtest import (
    basel_traffic_light,
    christoffersen_independence,
    kupiec_pof,
    rolling_var,
    run_backtest,
)


def _garch_returns(n: int, omega=2e-6, a=0.12, b=0.86, seed=5) -> np.ndarray:
    """Simulated GARCH(1,1) returns: volatility clusters, so a constant-window VaR should fail."""
    g = np.random.default_rng(seed)
    x = np.zeros(n)
    h = omega / (1 - a - b)
    for t in range(n):
        x[t] = math.sqrt(h) * g.standard_normal()
        h = omega + a * x[t] ** 2 + b * h
    return x


# ----------------------------- Kupiec POF -----------------------------


def test_kupiec_matches_hand_formula():
    T, N, c = 250, 6, 0.99
    p, pi = 1 - c, N / T
    expected = -2 * (
        ((T - N) * math.log(1 - p) + N * math.log(p))
        - ((T - N) * math.log(1 - pi) + N * math.log(pi))
    )
    res = kupiec_pof(N, T, c)
    assert res.lr_stat == pytest.approx(expected, rel=1e-12)
    assert res.p_value == pytest.approx(stats.chi2.sf(expected, df=1), rel=1e-12)


def test_kupiec_zero_exceptions_closed_form():
    # With N = 0 the unrestricted likelihood is 1, so LR = -2 * T * ln(1 - p).
    T, c = 250, 0.99
    res = kupiec_pof(0, T, c)
    assert res.lr_stat == pytest.approx(-2 * T * math.log(c), rel=1e-12)
    assert math.isfinite(res.p_value)
    assert res.reject  # a 99% VaR with zero exceptions in 250 days is too conservative


def test_kupiec_accepts_expected_count_and_rejects_far_from_it():
    assert not kupiec_pof(2, 250, 0.99).reject  # about 2.5 expected
    assert not kupiec_pof(3, 250, 0.99).reject
    assert kupiec_pof(10, 250, 0.99).reject


def test_kupiec_rejects_both_too_many_and_too_few():
    # The test is two-sided: coverage that is too conservative is also a model failure.
    assert kupiec_pof(0, 500, 0.99).reject
    assert kupiec_pof(20, 500, 0.99).reject


def test_kupiec_input_validation():
    with pytest.raises(ValueError):
        kupiec_pof(1, 0, 0.99)
    with pytest.raises(ValueError):
        kupiec_pof(11, 10, 0.99)
    with pytest.raises(ValueError):
        kupiec_pof(1, 10, 1.0)


# ------------------------ Christoffersen independence ------------------------


def _independence_reference(ex: np.ndarray) -> float:
    """Straight transcription of the textbook likelihood ratio, using explicit logs."""
    pairs = list(zip(ex[:-1], ex[1:]))
    n00 = sum(1 for a, b in pairs if not a and not b)
    n01 = sum(1 for a, b in pairs if not a and b)
    n10 = sum(1 for a, b in pairs if a and not b)
    n11 = sum(1 for a, b in pairs if a and b)
    pi01, pi11 = n01 / (n00 + n01), n11 / (n10 + n11)
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = (n00 + n10) * math.log(1 - pi) + (n01 + n11) * math.log(pi)
    ll1 = (
        n00 * math.log(1 - pi01)
        + n01 * math.log(pi01)
        + n10 * math.log(1 - pi11)
        + n11 * math.log(pi11)
    )
    return -2 * (ll0 - ll1)


def test_independence_matches_reference_formula():
    rng = np.random.default_rng(7)
    ex = rng.random(400) < 0.08
    ex[[10, 11, 12, 13]] = True  # make sure every transition type occurs
    res = christoffersen_independence(ex)
    assert res.lr_stat == pytest.approx(_independence_reference(ex), rel=1e-10)


def test_independence_flags_clusters_but_not_evenly_spaced_exceptions():
    n = 500
    clustered = np.zeros(n, dtype=bool)
    clustered[100:105] = True
    clustered[300:305] = True
    spread = np.zeros(n, dtype=bool)
    spread[::50] = True  # also 10 exceptions, but never on consecutive days

    assert christoffersen_independence(clustered).reject
    assert not christoffersen_independence(spread).reject


def test_independence_needs_two_observations():
    with pytest.raises(ValueError):
        christoffersen_independence(np.array([True]))


# ----------------------------- Basel zones -----------------------------


def test_basel_traffic_light_250_days_99pct_matches_published_table():
    zones = [basel_traffic_light(n, 250, 0.99) for n in range(0, 16)]
    assert zones[:5] == ["green"] * 5  # 0-4
    assert zones[5:10] == ["yellow"] * 5  # 5-9
    assert zones[10:] == ["red"] * 6  # 10+


def test_basel_traffic_light_is_monotone_in_exceptions():
    order = {"green": 0, "yellow": 1, "red": 2}
    zones = [order[basel_traffic_light(n, 500, 0.99)] for n in range(0, 40)]
    assert zones == sorted(zones)


# ----------------------------- rolling backtest -----------------------------


def test_rolling_var_has_no_lookahead():
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 400)
    base = rolling_var(r, 0.99, window=100, method="parametric")

    shocked = r.copy()
    shocked[105] = -0.5  # first used by the forecast for day 106 onwards (index 6)
    after = rolling_var(shocked, 0.99, window=100, method="parametric")

    np.testing.assert_array_equal(base[:6], after[:6])
    assert after[6] > base[6]


def test_rolling_var_validation():
    r = np.zeros(50)
    with pytest.raises(ValueError):
        rolling_var(r, 0.99, window=50)
    with pytest.raises(ValueError):
        rolling_var(np.zeros(100), 0.99, window=60, method="bogus")  # type: ignore[arg-type]


def test_parametric_backtest_passes_on_iid_normal_returns():
    r = np.random.default_rng(11).normal(0, 0.01, 3000)
    res = run_backtest(r, confidence=0.99, window=250, method="parametric")

    assert res.n_obs == 3000 - 250
    assert res.var_series.shape == res.exceptions.shape
    assert 0.005 <= res.kupiec.exception_rate <= 0.02
    assert not res.kupiec.reject
    assert not res.independence.reject
    assert res.traffic_light == "green"


def test_constant_window_models_fail_on_volatility_clustering_but_ewma_adapts():
    r = _garch_returns(4000)
    param = run_backtest(r, 0.99, 250, "parametric")
    hist = run_backtest(r, 0.99, 250, "historical")
    ewma = run_backtest(r, 0.99, 250, "ewma")

    # Constant-window VaR underestimates risk right after volatility jumps, so it gets
    # roughly twice the expected number of exceptions, and they arrive in clusters.
    assert param.kupiec.exception_rate > 0.015
    assert param.kupiec.reject
    assert param.independence.reject
    assert hist.kupiec.reject
    assert param.traffic_light == "red"

    # EWMA reweights recent data, so coverage is close to nominal.
    assert not ewma.kupiec.reject
    assert not ewma.independence.reject
    assert abs(ewma.kupiec.exception_rate - 0.01) < 0.005


def test_conditional_coverage_is_sum_of_the_two_statistics():
    r = _garch_returns(3000, seed=9)
    res = run_backtest(r, 0.99, 250, "parametric")
    assert res.conditional_coverage_lr == pytest.approx(
        res.kupiec.lr_stat + res.independence.lr_stat
    )
    assert res.conditional_coverage_p_value == pytest.approx(
        stats.chi2.sf(res.conditional_coverage_lr, df=2)
    )
