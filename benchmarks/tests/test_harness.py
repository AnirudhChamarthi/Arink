"""Checks on the benchmark harness itself: the simulated 'truth' must actually be true."""

import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dgp import TEST_DAYS, WINDOW, innovation_quantile, simulate  # noqa: E402
from run_simulated import basel_expected, run_path, tick_loss  # noqa: E402


def test_paths_are_deterministic_and_distinct():
    a, b = simulate("garch_t5", 3), simulate("garch_t5", 3)
    np.testing.assert_array_equal(a.returns, b.returns)
    assert not np.array_equal(a.returns, simulate("garch_t5", 4).returns)
    assert not np.array_equal(a.returns, simulate("garch_normal", 3).returns)


def test_path_lengths():
    p = simulate("normal_iid", 0)
    assert p.returns.shape == p.sigma.shape == (WINDOW + TEST_DAYS,)


@pytest.mark.parametrize("dgp", ["normal_iid", "garch_normal", "garch_t5", "regime_stress"])
@pytest.mark.parametrize("c", [0.975, 0.99])
def test_true_var_has_the_nominal_exception_rate(dgp, c):
    # Pool 60 paths x 1,250 days: if the 'true' VaR is right, exceptions occur at rate 1 - c.
    hits = n = 0
    for k in range(60):
        p = simulate(dgp, 1000 + k)
        hits += int((-p.returns > p.true_var(c)).sum())
        n += p.returns.size
    rate = hits / n
    se = np.sqrt((1 - c) * c / n)
    assert abs(rate - (1 - c)) < 4 * se, (rate, 1 - c)


def test_t_innovation_quantile_is_for_a_unit_variance_t():
    rng = np.random.default_rng(0)
    eps = rng.standard_t(5, 2_000_000) * np.sqrt(3 / 5)
    assert eps.var() == pytest.approx(1.0, abs=0.01)
    assert np.quantile(eps, 0.99) == pytest.approx(innovation_quantile("t5", 0.99), abs=0.01)


def test_regime_stress_triples_volatility_in_the_declared_window():
    s = simulate("regime_stress", 0).sigma
    assert s[WINDOW + 399] == 0.008 and s[WINDOW + 400] == 0.024
    assert s[WINDOW + 524] == 0.024 and s[WINDOW + 525] == 0.008


def test_basel_expected_matches_the_published_zone_boundaries():
    e = basel_expected()
    assert e["green"] == pytest.approx(stats.binom.cdf(4, 250, 0.01))
    assert e["green"] == pytest.approx(0.8922, abs=1e-4)
    assert sum(e.values()) == pytest.approx(1.0)


def test_tick_loss_is_minimised_at_the_true_quantile():
    rng = np.random.default_rng(1)
    losses = rng.standard_normal(400_000)
    q = stats.norm.ppf(0.99)
    best = tick_loss(losses, np.full_like(losses, q), 0.99).mean()
    for shift in (-0.3, -0.1, 0.1, 0.3):
        assert tick_loss(losses, np.full_like(losses, q + shift), 0.99).mean() > best


def test_oracle_row_scores_zero_bias_and_zero_excess_tick_loss():
    s = run_path(("garch_normal", 0))["scores"]
    o = s["oracle (true VaR)|0.99"]
    assert o["rel_bias"] == 0.0 and o["rel_sq"] == 0.0 and o["tick"] == o["tick_oracle"]
    assert len(o["zones"]) == TEST_DAYS // 250


def test_forecasts_use_only_past_data():
    # Changing the last return must not change any forecast up to and including that day.
    p = simulate("garch_normal", 0)
    from models.backtest import rolling_var

    base = rolling_var(p.returns, 0.99, window=WINDOW, method="ewma")
    bumped = p.returns.copy()
    bumped[-1] = -0.5
    np.testing.assert_array_equal(base, rolling_var(bumped, 0.99, window=WINDOW, method="ewma"))
