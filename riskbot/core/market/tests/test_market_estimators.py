"""Independent oracles for every formula in ``riskbot.core.market.estimators``."""

import math

import numpy as np
import pytest
from scipy import integrate, stats

from riskbot.core.market import estimators as E
from riskbot.core.market.var_model import rolling_forecasts

# --------------------------------------------------------------------------------------------
# Parametric VaR / ES
# --------------------------------------------------------------------------------------------


def test_normal_var_es_closed_form_published_values():
    # z_0.99 = 2.326348, phi(z)/(1-c) = 2.665214 (standard tables)
    var, es = E.normal_var_es(0.01, 0.99)
    assert var == pytest.approx(0.02326348, rel=1e-6)
    assert es == pytest.approx(0.02665214, rel=1e-6)
    # 97.5% ES of a normal equals roughly the 99% VaR (the Basel FRTB calibration argument)
    es975 = E.normal_var_es(1.0, 0.975)[1]
    assert es975 == pytest.approx(2.3378, abs=1e-4)


def test_normal_es_matches_numerical_tail_integral():
    sigma, c = 0.013, 0.99
    var, es = E.normal_var_es(sigma, c)
    tail, _ = integrate.quad(lambda x: x * stats.norm.pdf(x, scale=sigma), var, np.inf)
    assert es == pytest.approx(tail / (1 - c), rel=1e-8)


@pytest.mark.parametrize("nu", [3.0, 5.0, 12.0])
@pytest.mark.parametrize("c", [0.95, 0.99, 0.999])
def test_student_t_var_es_vs_numerical_integration(nu, c):
    sigma = 0.02
    scale = sigma * math.sqrt((nu - 2) / nu)
    dist = stats.t(nu, scale=scale)
    assert dist.std() == pytest.approx(sigma, rel=1e-10)  # unit-variance scaling oracle
    var, es = E.student_t_var_es(sigma, c, nu)
    assert var == pytest.approx(dist.ppf(c), rel=1e-10)
    # ES as the average of VaR_u for u in (c, 1)
    es_q, _ = integrate.quad(lambda u: dist.ppf(u), c, 1, limit=200)
    assert es == pytest.approx(es_q / (1 - c), rel=1e-6)
    # and as the conditional tail expectation
    es_x, _ = integrate.quad(lambda x: x * dist.pdf(x), var, np.inf, limit=200)
    assert es == pytest.approx(es_x / (1 - c), rel=1e-6)


def test_student_t_converges_to_normal_for_large_dof():
    v_t, e_t = E.student_t_var_es(0.01, 0.99, 1e6)
    v_n, e_n = E.normal_var_es(0.01, 0.99)
    assert v_t == pytest.approx(v_n, rel=1e-4) and e_t == pytest.approx(e_n, rel=1e-4)


# --------------------------------------------------------------------------------------------
# Empirical
# --------------------------------------------------------------------------------------------


def test_historical_equals_numpy_quantile_and_tail_mean():
    rng = np.random.default_rng(3)
    L = rng.standard_t(4, size=777) * 0.01
    for c in (0.9, 0.975, 0.99):
        var, es = E.empirical_var_es(L, c)
        assert var == np.quantile(L, c)
        assert es == pytest.approx(L[L >= np.quantile(L, c)].mean(), rel=1e-12)
        assert es >= var


def test_empirical_known_small_sample():
    L = np.arange(1.0, 101.0)  # 1..100
    var, es = E.empirical_var_es(L, 0.95)
    assert var == pytest.approx(95.05)  # linear interpolation: 1 + 0.95 * 99
    assert es == pytest.approx(np.mean(np.arange(96.0, 101.0)))


# --------------------------------------------------------------------------------------------
# Covariance: Ledoit-Wolf constant correlation
# --------------------------------------------------------------------------------------------


def _lw_loop_oracle(R):
    """Direct transcription of Ledoit & Wolf (2004), Appendix, with explicit loops."""
    T, N = R.shape
    Y = R - R.mean(axis=0)
    S = Y.T @ Y / T
    rbar = 0.0
    for i in range(N):
        for j in range(N):
            if i != j:
                rbar += S[i, j] / math.sqrt(S[i, i] * S[j, j])
    rbar /= N * (N - 1)
    F = np.empty((N, N))
    for i in range(N):
        for j in range(N):
            F[i, j] = S[i, i] if i == j else rbar * math.sqrt(S[i, i] * S[j, j])
    pi = rho = gamma = 0.0
    for i in range(N):
        for j in range(N):
            pij = np.mean((Y[:, i] * Y[:, j] - S[i, j]) ** 2)
            pi += pij
            gamma += (F[i, j] - S[i, j]) ** 2
            if i == j:
                rho += pij
            else:
                th_ii = np.mean((Y[:, i] ** 2 - S[i, i]) * (Y[:, i] * Y[:, j] - S[i, j]))
                th_jj = np.mean((Y[:, j] ** 2 - S[j, j]) * (Y[:, i] * Y[:, j] - S[i, j]))
                rho += rbar / 2 * (math.sqrt(S[j, j] / S[i, i]) * th_ii + math.sqrt(S[i, i] / S[j, j]) * th_jj)
    delta = max(0.0, min(1.0, (pi - rho) / gamma / T))
    return (delta * F + (1 - delta) * S) * T / (T - 1), delta


def _true_sigma(N, rho=0.4, seed=0):
    vols = np.linspace(0.01, 0.03, N)
    C = np.full((N, N), rho)
    np.fill_diagonal(C, 1.0)
    return C * np.outer(vols, vols)


def test_ledoit_wolf_matches_loop_oracle():
    rng = np.random.default_rng(11)
    R = rng.multivariate_normal(np.zeros(6), _true_sigma(6), size=40)
    S, d = E.ledoit_wolf_cc(R)
    S2, d2 = _lw_loop_oracle(R)
    assert d == pytest.approx(d2, rel=1e-10)
    np.testing.assert_allclose(S, S2, rtol=1e-10)


def test_ledoit_wolf_intensity_pd_and_lower_frobenius_error():
    N, T, reps = 10, 30, 60
    Sigma = _true_sigma(N, 0.4)
    rng = np.random.default_rng(7)
    err_s, err_lw = [], []
    for _ in range(reps):
        R = rng.multivariate_normal(np.zeros(N), Sigma, size=T)
        Slw, d = E.ledoit_wolf_cc(R)
        assert 0.0 <= d <= 1.0
        assert np.linalg.eigvalsh(Slw).min() > 0  # positive definite even though T is small
        np.testing.assert_allclose(Slw, Slw.T)
        err_lw.append(np.linalg.norm(Slw - Sigma, "fro"))
        err_s.append(np.linalg.norm(E.sample_cov(R) - Sigma, "fro"))
    assert np.mean(err_lw) < np.mean(err_s)


def test_ledoit_wolf_intensity_shrinks_with_sample_size():
    # heterogeneous correlations: the target is misspecified, so the optimal intensity -> 0 as T grows
    # (with a constant-correlation truth it would stay near 1, which is also correct).
    C = np.array([[1, .8, .1, .1, .0], [.8, 1, .1, .1, .0], [.1, .1, 1, .7, .2],
                  [.1, .1, .7, 1, .2], [.0, .0, .2, .2, 1]])
    vols = np.array([0.01, 0.015, 0.02, 0.012, 0.03])
    Sigma = C * np.outer(vols, vols)
    rng = np.random.default_rng(5)
    small = np.mean([E.ledoit_wolf_cc(rng.multivariate_normal(np.zeros(5), Sigma, 30))[1] for _ in range(20)])
    large = np.mean([E.ledoit_wolf_cc(rng.multivariate_normal(np.zeros(5), Sigma, 3000))[1] for _ in range(5)])
    assert large < small


def test_ledoit_wolf_single_asset_is_sample_variance():
    R = np.random.default_rng(1).standard_normal((50, 1))
    S, d = E.ledoit_wolf_cc(R)
    assert d == 0.0 and S[0, 0] == pytest.approx(np.var(R, ddof=1))


# --------------------------------------------------------------------------------------------
# GARCH / FHS
# --------------------------------------------------------------------------------------------


def _sim_garch(n, omega, alpha, beta, seed):
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n + 500)
    x = np.empty(n + 500)
    s2 = omega / (1 - alpha - beta)
    prev = 0.0
    for t in range(n + 500):
        s2 = omega + alpha * prev**2 + beta * s2
        prev = math.sqrt(s2) * z[t]
        x[t] = prev
    return x[500:]


def test_garch_filter_matches_arch_conditional_volatility_and_forecast():
    from arch import arch_model

    x = _sim_garch(600, 0.05, 0.1, 0.85, seed=2)
    res = arch_model(x, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False).fit(disp="off")
    o, a, b = res.params.values
    s2, s2n = E.garch_filter(x, o, a, b)
    np.testing.assert_allclose(np.sqrt(s2), res.conditional_volatility, rtol=1e-10)
    assert s2n == pytest.approx(float(res.forecast(horizon=1, reindex=False).variance.values[-1, 0]), rel=1e-10)


def test_garch_fit_recovers_parameters():
    x = _sim_garch(4000, 0.05, 0.10, 0.85, seed=4)
    fit = E.fit_garch(x)
    assert fit.converged
    assert fit.alpha == pytest.approx(0.10, abs=0.04)
    assert fit.beta == pytest.approx(0.85, abs=0.06)


def test_ewma_filter_recursion():
    x = np.array([1.0, -2.0, 0.5, 3.0])
    s2, nxt = E.ewma_filter(x, 0.94)
    exp = [np.mean(x**2)]
    for v in x:
        exp.append(0.94 * exp[-1] + 0.06 * v**2)
    np.testing.assert_allclose(s2, exp[:-1])
    assert nxt == pytest.approx(exp[-1])


def test_fhs_rolling_exception_rate_near_target_on_simulated_garch():
    # simulated GARCH(1,1) data with normal shocks, daily vol ~1%; 95% VaR -> expect 5% exceptions
    r = _sim_garch(1450, 0.05, 0.08, 0.90, seed=21) / 100.0
    eff = {"confidence": 0.95, "horizon_days": 1}
    fc = rolling_forecasts("fhs", r[:, None], np.array([1.0]), eff, window=250)
    rate = np.mean(fc.losses > fc.var)
    assert fc.var.size == 1200
    assert 0.035 <= rate <= 0.068
    # the filtered forecast tracks volatility: unfiltered historical VaR has more clustered exceptions
    hits = (fc.losses > fc.var).astype(int)
    assert E.christoffersen_independence(hits)[1] > 0.01


# --------------------------------------------------------------------------------------------
# EVT
# --------------------------------------------------------------------------------------------


def test_gpd_fast_fit_agrees_with_scipy():
    for seed in range(6):
        y = stats.genpareto.rvs(0.25, scale=0.01, size=60, random_state=seed)
        xi_f, b_f = E.gpd_fit_fast(y)
        xi_s, b_s = E.gpd_fit_scipy(y)
        nll = lambda xi, b: -stats.genpareto.logpdf(y, xi, 0, b).sum()  # noqa: E731
        assert nll(xi_f, b_f) <= nll(xi_s, b_s) + 1e-6  # at least as good a maximum
        assert xi_f == pytest.approx(xi_s, abs=0.03)


def test_evt_recovers_xi_from_simulated_gpd_tails():
    # Pure GPD losses: by threshold stability, exceedances over any u are GPD with the same xi.
    L = stats.genpareto.rvs(0.25, scale=0.01, size=20000, random_state=42)
    for fast in (False, True):
        ev = E.evt_var_es(-L, 0.999, 0.9, fast=fast)
        assert ev.xi == pytest.approx(0.25, abs=0.06)
        true_q = stats.genpareto.ppf(0.999, 0.25, scale=0.01)
        assert ev.var == pytest.approx(true_q, rel=0.06)
    # Student-t(4) losses have tail index 1/4
    Lt = stats.t.rvs(4, size=40000, random_state=7)
    assert E.evt_var_es(-Lt, 0.999, 0.95).xi == pytest.approx(0.25, abs=0.1)


def test_evt_quantile_and_es_closed_forms():
    xi, beta = 0.3, 0.02
    # with u = 0 and N_u = n, the POT quantile is the GPD quantile
    for c in (0.9, 0.99, 0.999):
        assert E.evt_quantile(0.0, xi, beta, 100, 100, c) == pytest.approx(stats.genpareto.ppf(c, xi, scale=beta))
        var = E.evt_quantile(0.0, xi, beta, 100, 100, c)
        tail, _ = integrate.quad(lambda x: x * stats.genpareto.pdf(x, xi, scale=beta), var, np.inf)
        assert E.evt_es(var, 0.0, xi, beta) == pytest.approx(tail / (1 - c), rel=1e-6)
    # exponential limit is continuous in xi
    a = E.evt_quantile(0.01, 0.0, beta, 250, 25, 0.99)
    b = E.evt_quantile(0.01, 1e-5, beta, 250, 25, 0.99)
    assert a == pytest.approx(b, rel=1e-4)
    with pytest.raises(ValueError):
        E.evt_es(0.1, 0.0, 1.0, beta)


def test_evt_needs_twenty_exceedances():
    with pytest.raises(ValueError, match="exceedances"):
        E.evt_var_es(np.random.default_rng(0).standard_normal(150), 0.99, 0.9)


# --------------------------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------------------------


def test_montecarlo_converges_to_normal_for_zero_mean():
    Sigma = _true_sigma(4, 0.5)
    w = np.array([0.4, -0.2, 0.3, 0.1])
    Z = np.random.default_rng(0).standard_normal((400000, 4))
    h, c = 5, 0.99
    losses = E.montecarlo_losses(np.zeros(4), Sigma, w, h, Z)
    var, es = E.empirical_var_es(losses, c)
    v_n, e_n = E.normal_var_es(math.sqrt(w @ Sigma @ w), c)
    assert var == pytest.approx(v_n * math.sqrt(h), rel=0.01)
    assert es == pytest.approx(e_n * math.sqrt(h), rel=0.015)


def test_chol_psd_handles_singular_matrix():
    S = np.array([[1.0, 1.0], [1.0, 1.0]])
    L = E.chol_psd(S)
    np.testing.assert_allclose(L @ L.T, S, atol=1e-12)


# --------------------------------------------------------------------------------------------
# Backtest statistics
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n,x,p", [(250, 0, 0.01), (250, 2, 0.01), (250, 10, 0.01), (500, 40, 0.05)])
def test_kupiec_equals_binomial_likelihood_ratio(n, x, p):
    lr, pv = E.kupiec_pof(n, x, p)
    # oracle: binomial coefficients cancel in the ratio
    oracle = 2 * (stats.binom.logpmf(x, n, x / n) - stats.binom.logpmf(x, n, p))
    assert lr == pytest.approx(oracle, abs=1e-9)
    assert pv == pytest.approx(stats.chi2.sf(oracle, 1), abs=1e-12)


def test_kupiec_published_value():
    # 250 days, 99% VaR, 10 exceptions: LR ~ 12.95, rejected at 1% (Jorion, Value at Risk, ch. 6)
    lr, pv = E.kupiec_pof(250, 10, 0.01)
    assert lr == pytest.approx(12.96, abs=0.02)
    assert pv < 0.001


def test_christoffersen_independence():
    rng = np.random.default_rng(1)
    hits = (rng.random(2000) < 0.05).astype(int)
    lr, pv, counts = E.christoffersen_independence(hits)
    assert sum(counts.values()) == 1999
    # oracle: Markov vs Bernoulli log-likelihoods by brute force
    a, b = hits[:-1], hits[1:]
    pi = b.mean()
    pi0 = b[a == 0].mean()
    pi1 = b[a == 1].mean()
    ll1 = np.sum(np.where(a == 0, np.where(b == 1, np.log(pi0), np.log(1 - pi0)),
                          np.where(b == 1, np.log(pi1), np.log(1 - pi1))))
    ll0 = np.sum(np.where(b == 1, np.log(pi), np.log(1 - pi)))
    assert lr == pytest.approx(2 * (ll1 - ll0), rel=1e-9)
    assert pv > 0.01
    clustered = np.zeros(500, dtype=int)
    clustered[100:110] = 1
    clustered[300:310] = 1
    assert E.christoffersen_independence(clustered)[1] < 1e-4


def test_basel_zones_match_published_table():
    # Basel Committee (1996) traffic light at 99%, 250 days: green 0-4, yellow 5-9, red >= 10
    zones = [E.basel_zone(x, 250, 0.01)[0] for x in range(13)]
    assert zones == ["green"] * 5 + ["yellow"] * 5 + ["red"] * 3


# --------------------------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------------------------


def test_moving_block_indices():
    rng = np.random.default_rng(0)
    assert E.block_length(250) == 6 and E.block_length(750) == 9
    idx = E.moving_block_indices(250, rng)
    assert idx.shape == (250,) and idx.min() >= 0 and idx.max() < 250
    blocks = idx[: 6 * 41].reshape(41, 6)
    assert np.all(np.diff(blocks, axis=1) == 1)  # contiguous within blocks
