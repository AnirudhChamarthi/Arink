"""Pure numerical building blocks for the Q1 market-risk models.

Everything here works on plain numpy arrays (no contract types) so that each formula can be tested
against an independent oracle. Conventions:

* ``r`` is a 1-D array of *simple* daily portfolio returns, ``R`` a ``(n, k)`` matrix of asset returns.
* Losses are positive: ``L = -r``.
* ``c`` is the VaR confidence level (e.g. 0.99); all VaR/ES values returned are 1-day, positive
  fractions of gross exposure unless stated otherwise.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, signal, stats

# --------------------------------------------------------------------------------------------
# Covariance estimators
# --------------------------------------------------------------------------------------------


def sample_cov(R: np.ndarray) -> np.ndarray:
    """Unbiased sample covariance :math:`S = \\frac{1}{n-1}\\sum_t (R_t-\\bar R)(R_t-\\bar R)^\\top`."""
    return np.atleast_2d(np.cov(R, rowvar=False, ddof=1))


def ledoit_wolf_cc(R: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage towards the constant-correlation target.

    Ledoit, O. and Wolf, M. (2004), "Honey, I shrunk the sample covariance matrix",
    Journal of Portfolio Management 30(4), 110-119.

    With demeaned returns :math:`y_{ti}`, :math:`s_{ij} = \\frac1T\\sum_t y_{ti}y_{tj}` and average
    correlation :math:`\\bar r`, the target is :math:`f_{ii}=s_{ii}`, :math:`f_{ij}=\\bar r\\sqrt{s_{ii}s_{jj}}`.
    The optimal intensity is :math:`\\delta^*=\\max(0,\\min(1,\\hat\\kappa/T))` with
    :math:`\\hat\\kappa=(\\hat\\pi-\\hat\\rho)/\\hat\\gamma`, where

    * :math:`\\hat\\pi=\\sum_{ij}\\frac1T\\sum_t (y_{ti}y_{tj}-s_{ij})^2`,
    * :math:`\\hat\\rho=\\sum_i\\hat\\pi_{ii}+\\sum_{i\\ne j}\\frac{\\bar r}{2}
      \\big(\\sqrt{s_{jj}/s_{ii}}\\,\\hat\\vartheta_{ii,ij}+\\sqrt{s_{ii}/s_{jj}}\\,\\hat\\vartheta_{jj,ij}\\big)`,
      :math:`\\hat\\vartheta_{ii,ij}=\\frac1T\\sum_t (y_{ti}^2-s_{ii})(y_{ti}y_{tj}-s_{ij})`,
    * :math:`\\hat\\gamma=\\sum_{ij}(f_{ij}-s_{ij})^2`.

    The shrunk matrix :math:`\\delta^* F + (1-\\delta^*) S` is computed on the 1/T basis of the paper and then
    multiplied by :math:`T/(T-1)`, so that :math:`\\delta^*=0` reproduces :func:`sample_cov` exactly.

    Returns ``(sigma, delta)``.
    """
    R = np.asarray(R, dtype=float)
    T, N = R.shape
    if N == 1:
        return sample_cov(R), 0.0
    Y = R - R.mean(axis=0)
    S = Y.T @ Y / T
    sd = np.sqrt(np.diag(S))
    if np.any(sd <= 0):
        return sample_cov(R), 0.0
    corr = S / np.outer(sd, sd)
    rbar = (corr.sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, np.diag(S))

    Y2 = Y**2
    # pi_ij = mean_t (y_ti y_tj - s_ij)^2 = mean(y_i^2 y_j^2) - s_ij^2
    pi_mat = Y2.T @ Y2 / T - S**2
    pi_hat = pi_mat.sum()
    # theta_ii,ij = mean_t (y_ti^2 - s_ii)(y_ti y_tj - s_ij) = mean(y_i^3 y_j) - s_ii s_ij
    theta = (Y**3).T @ Y / T - np.diag(S)[:, None] * S  # theta[i, j] = theta_{ii,ij}
    ratio = np.outer(1.0 / sd, sd)  # ratio[i, j] = sqrt(s_jj / s_ii)
    off = rbar / 2.0 * (ratio * theta + ratio.T * theta.T)
    np.fill_diagonal(off, 0.0)
    rho_hat = np.trace(pi_mat) + off.sum()
    gamma_hat = ((F - S) ** 2).sum()
    if gamma_hat <= 0:
        delta = 0.0
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(max(0.0, min(1.0, kappa / T)))
    sigma = (delta * F + (1.0 - delta) * S) * T / (T - 1)
    return sigma, delta


def covariance(R: np.ndarray, kind: str) -> tuple[np.ndarray, float | None]:
    """Dispatch: ``'sample'`` -> (S, None); ``'ledoit_wolf'`` -> (shrunk, intensity)."""
    if kind == "ledoit_wolf":
        return ledoit_wolf_cc(R)
    return sample_cov(R), None


# --------------------------------------------------------------------------------------------
# Parametric VaR / ES
# --------------------------------------------------------------------------------------------


def normal_var_es(sigma: float, c: float) -> tuple[float, float]:
    """Zero-mean Gaussian: :math:`VaR=z_c\\sigma`, :math:`ES=\\sigma\\,\\varphi(z_c)/(1-c)`."""
    z = stats.norm.ppf(c)
    return float(z * sigma), float(sigma * stats.norm.pdf(z) / (1.0 - c))


def student_t_var_es(sigma: float, c: float, nu: float) -> tuple[float, float]:
    """Student-t with :math:`\\nu` dof rescaled to unit variance, then multiplied by :math:`\\sigma`.

    :math:`VaR=\\sigma\\,t_\\nu^{-1}(c)\\sqrt{(\\nu-2)/\\nu}`,
    :math:`ES=\\sigma\\sqrt{(\\nu-2)/\\nu}\\,\\frac{f_\\nu(t_c)}{1-c}\\,\\frac{\\nu+t_c^2}{\\nu-1}`.
    """
    if nu <= 2:
        raise ValueError("t_dof must exceed 2 for a finite variance")
    tc = stats.t.ppf(c, nu)
    scale = math.sqrt((nu - 2.0) / nu)
    var = sigma * tc * scale
    es = sigma * scale * stats.t.pdf(tc, nu) / (1.0 - c) * (nu + tc**2) / (nu - 1.0)
    return float(var), float(es)


# --------------------------------------------------------------------------------------------
# Empirical VaR / ES
# --------------------------------------------------------------------------------------------


def empirical_var_es(losses: np.ndarray, c: float) -> tuple[float, float]:
    """VaR = ``np.quantile(L, c)`` (linear interpolation); ES = mean of losses ``>= VaR``."""
    losses = np.asarray(losses, dtype=float)
    var = float(np.quantile(losses, c))
    tail = losses[losses >= var]
    es = float(tail.mean()) if tail.size else var
    return var, es


# --------------------------------------------------------------------------------------------
# GARCH(1,1) and EWMA filters
# --------------------------------------------------------------------------------------------


def arch_backcast(x: np.ndarray) -> float:
    """The ``arch`` package's initial variance: exponentially weighted (0.94) mean of the first 75 x^2."""
    tau = min(75, x.shape[0])
    w = 0.94 ** np.arange(tau)
    w = w / w.sum()
    return float(np.sum(x[:tau] ** 2 * w))


def garch_filter(x: np.ndarray, omega: float, alpha: float, beta: float,
                 init: float | None = None) -> tuple[np.ndarray, float]:
    """Conditional variances of a zero-mean GARCH(1,1) with fixed parameters.

    :math:`\\sigma_t^2=\\omega+\\alpha x_{t-1}^2+\\beta\\sigma_{t-1}^2`, with the pre-sample values
    :math:`x_{-1}^2=\\sigma_{-1}^2=` backcast (same convention as ``arch``). Implemented as a linear filter.
    Returns ``(sigma2[0..T-1], sigma2_{T})`` (the one-step-ahead forecast).
    """
    x = np.asarray(x, dtype=float)
    bc = arch_backcast(x) if init is None else init
    drive = omega + alpha * np.concatenate(([bc], x**2))  # length T+1: drives sigma2_0..sigma2_T
    zi = np.array([beta * bc])
    s2, _ = signal.lfilter([1.0], [1.0, -beta], drive, zi=zi)
    return s2[:-1], float(s2[-1])


def ewma_filter(x: np.ndarray, lam: float = 0.94) -> tuple[np.ndarray, float]:
    """RiskMetrics EWMA: :math:`\\sigma_t^2=\\lambda\\sigma_{t-1}^2+(1-\\lambda)x_{t-1}^2`,
    :math:`\\sigma_0^2=\\overline{x^2}` (window mean). Returns ``(sigma2[0..T-1], sigma2_T)``."""
    x = np.asarray(x, dtype=float)
    s0 = float(np.mean(x**2))
    drive = np.concatenate(([s0], (1.0 - lam) * x**2))
    s2 = signal.lfilter([1.0], [1.0, -lam], drive)
    return s2[:-1], float(s2[-1])


@dataclass
class GarchFit:
    omega: float
    alpha: float
    beta: float
    converged: bool
    loglik: float | None = None
    message: str = ""


def fit_garch(x: np.ndarray, starting: tuple[float, float, float] | None = None) -> GarchFit:
    """Fit a zero-mean, Gaussian GARCH(1,1) with ``arch`` (x in percent). Never raises.

    ``converged`` is False if the optimiser fails, the parameters are not finite / not positive, or
    :math:`\\alpha+\\beta>1` (explosive). ``arch`` constrains :math:`\\alpha+\\beta\\le1`; a fit on that
    boundary (integrated GARCH) is accepted because the one-step forecast stays finite.
    """
    from arch import arch_model  # local import keeps module import cheap

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            am = arch_model(x, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False)
            sv = None if starting is None else np.asarray(starting, dtype=float)
            res = am.fit(disp="off", starting_values=sv, show_warning=False)
        omega, alpha, beta = (float(v) for v in res.params.values)
        ok = (res.convergence_flag == 0 and all(math.isfinite(v) for v in (omega, alpha, beta))
              and omega > 0 and alpha >= 0 and beta >= 0 and alpha + beta <= 1.0 + 1e-8)
        return GarchFit(omega, alpha, beta, ok, float(res.loglikelihood),
                        "" if ok else f"convergence_flag={res.convergence_flag}, alpha+beta={alpha + beta:.4f}")
    except Exception as exc:  # noqa: BLE001 - any optimiser failure means fallback
        return GarchFit(float("nan"), float("nan"), float("nan"), False, None, f"{type(exc).__name__}: {exc}")


@dataclass
class FhsResult:
    var: float
    es: float
    sigma_next: float  # decimal units
    filter: str  # "garch" or "ewma"
    fit: GarchFit | None
    z: np.ndarray = field(repr=False)


def fhs_var_es(r: np.ndarray, c: float, *, params: tuple[float, float, float] | None = None,
               starting: tuple[float, float, float] | None = None,
               condition_on: np.ndarray | None = None, force_ewma: bool = False) -> FhsResult:
    """Filtered historical simulation (Barone-Adesi et al. 1999; Hull & White 1998).

    Fit GARCH(1,1) to :math:`x=100r`, standardise :math:`z_t=x_t/\\sigma_t`, forecast
    :math:`\\sigma_{T+1}`, and take the empirical quantile / tail mean of simulated losses
    :math:`-\\sigma_{T+1}z_t/100`. With ``params`` given, no fit is done (fixed-parameter filter).
    Falls back to EWMA(0.94) if the fit fails (or always, with ``force_ewma``).

    ``condition_on``: if given (bootstrap use), the residuals come from ``r`` but the forecast
    :math:`\\sigma_{T+1}` is obtained by filtering this (actual) series, so the forecast stays conditional on
    the observed recent history.
    """
    x = 100.0 * np.asarray(r, dtype=float)
    xc = x if condition_on is None else 100.0 * np.asarray(condition_on, dtype=float)
    fit: GarchFit | None
    if force_ewma:
        fit = GarchFit(float("nan"), float("nan"), float("nan"), False, None, "EWMA requested")
    elif params is not None:
        fit = GarchFit(*params, converged=True)
    else:
        fit = fit_garch(x, starting)
    if fit.converged:
        s2, s2_next = garch_filter(x, fit.omega, fit.alpha, fit.beta)
        if condition_on is not None:
            s2_next = garch_filter(xc, fit.omega, fit.alpha, fit.beta)[1]
        kind = "garch"
    else:
        s2, s2_next = ewma_filter(x)
        if condition_on is not None:
            s2_next = ewma_filter(xc)[1]
        kind = "ewma"
    z = x / np.sqrt(s2)
    sig_next = math.sqrt(s2_next)
    var, es = empirical_var_es(-sig_next * z / 100.0, c)
    return FhsResult(var, es, sig_next / 100.0, kind, fit, z)


# --------------------------------------------------------------------------------------------
# Extreme value theory: peaks over threshold with a generalized Pareto tail
# --------------------------------------------------------------------------------------------

MIN_EXCEEDANCES = 20


def gpd_fit_fast(y: np.ndarray) -> tuple[float, float]:
    """Maximum-likelihood GPD fit (loc = 0) via the profile likelihood (Grimshaw 1993).

    With :math:`\\theta=\\xi/\\beta`, the MLE of :math:`\\xi` given :math:`\\theta` is
    :math:`\\hat\\xi(\\theta)=\\frac1n\\sum\\log(1+\\theta y_i)` and the profile log-likelihood is
    :math:`\\ell^*(\\theta)=-n\\log(\\hat\\xi/\\theta)-n\\hat\\xi-n`. It is maximised on a grid over
    :math:`\\theta\\in(-1/y_{max},\\infty)` and refined with bounded Brent. Used inside the bootstrap and
    backtest (hundreds of fits); tested to agree with ``scipy.stats.genpareto.fit``.
    Returns ``(xi, beta)``.
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    ymax, ybar = float(y.max()), float(y.mean())
    lo = -1.0 / ymax

    def prof(theta: np.ndarray) -> np.ndarray:
        theta = np.atleast_1d(theta)
        small = np.abs(theta) < 1e-12
        th = np.where(small, 1e-12, theta)
        m = np.log1p(np.outer(th, y)).mean(axis=1)
        ratio = np.where(small, ybar, m / th)
        m = np.where(small, 0.0, m)
        return -n * np.log(ratio) - n * m - n

    # grid: dense near the lower bound and log-spaced on the positive side
    neg = lo * (1.0 - np.geomspace(1e-6, 1.0, 60))[::-1]  # from ~lo to 0
    pos = np.geomspace(1e-4, 1e3, 80) / ybar
    grid = np.concatenate((neg[:-1], [0.0], pos))
    vals = prof(grid)
    vals[~np.isfinite(vals)] = -np.inf
    i = int(np.argmax(vals))
    a = grid[max(i - 1, 0)]
    b = grid[min(i + 1, grid.size - 1)]
    if b > a:
        res = optimize.minimize_scalar(lambda t: -float(prof(t)[0]), bounds=(a, b), method="bounded",
                                       options={"xatol": 1e-10 / ybar})
        theta = float(res.x) if -res.fun >= vals[i] else float(grid[i])
    else:
        theta = float(grid[i])
    if abs(theta) < 1e-12:
        return 0.0, ybar
    xi = float(np.log1p(theta * y).mean())
    return xi, xi / theta


def gpd_fit_scipy(y: np.ndarray) -> tuple[float, float]:
    """Reference MLE with ``scipy.stats.genpareto.fit(y, floc=0)``. Returns ``(xi, beta)``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xi, _, beta = stats.genpareto.fit(y, floc=0)
    return float(xi), float(beta)


def evt_quantile(u: float, xi: float, beta: float, n: int, n_u: int, c: float) -> float:
    """POT quantile: :math:`VaR=u+\\frac{\\beta}{\\xi}\\big[(\\tfrac{n}{N_u}(1-c))^{-\\xi}-1\\big]`,
    exponential limit :math:`u-\\beta\\log(\\tfrac{n}{N_u}(1-c))` when :math:`|\\xi|<10^{-6}`."""
    p = n / n_u * (1.0 - c)
    if abs(xi) < 1e-6:
        return float(u - beta * math.log(p))
    return float(u + beta / xi * (p ** (-xi) - 1.0))


def evt_es(var: float, u: float, xi: float, beta: float) -> float:
    """POT expected shortfall :math:`ES=(VaR+\\beta-\\xi u)/(1-\\xi)`, finite only for :math:`\\xi<1`."""
    if xi >= 1.0:
        raise ValueError("ES is infinite for xi >= 1")
    return float((var + beta - xi * u) / (1.0 - xi))


@dataclass
class EvtResult:
    var: float
    es: float | None
    u: float
    xi: float
    beta: float
    n: int
    n_u: int


def evt_var_es(r: np.ndarray, c: float, q: float, *, fast: bool = False) -> EvtResult:
    """Peaks over threshold on losses :math:`L=-r`: :math:`u=` quantile(L, q), exceedances
    :math:`y=L-u` for :math:`L>u`, GPD fitted by MLE. Raises ``ValueError`` if fewer than 20 exceedances."""
    L = -np.asarray(r, dtype=float)
    u = float(np.quantile(L, q))
    y = L[L > u] - u
    n, n_u = L.size, int(y.size)
    if n_u < MIN_EXCEEDANCES:
        raise ValueError(f"only {n_u} exceedances over the threshold (need >= {MIN_EXCEEDANCES})")
    xi, beta = gpd_fit_fast(y) if fast else gpd_fit_scipy(y)
    var = evt_quantile(u, xi, beta, n, n_u, c)
    es = evt_es(var, u, xi, beta) if xi < 1.0 else None
    return EvtResult(var, es, u, xi, beta, n, n_u)


# --------------------------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------------------------


def chol_psd(S: np.ndarray) -> np.ndarray:
    """Cholesky factor; falls back to a symmetric square root for semi-definite matrices."""
    try:
        return np.linalg.cholesky(S)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh((S + S.T) / 2.0)
        return vecs * np.sqrt(np.clip(vals, 0.0, None))


def montecarlo_losses(mu: np.ndarray, S: np.ndarray, w: np.ndarray, h: int, Z: np.ndarray) -> np.ndarray:
    """Portfolio losses for draws :math:`X=h\\mu+\\sqrt h\\,ZL^\\top\\sim N(h\\mu,h\\Sigma)`, loss :math:`=-Xw`.
    ``Z`` is an ``(n_sims, k)`` array of independent standard normals."""
    X = h * mu + math.sqrt(h) * Z @ chol_psd(S).T
    return -(X @ w)


# --------------------------------------------------------------------------------------------
# Backtest statistics
# --------------------------------------------------------------------------------------------


def _xlogy(x: float, y: float) -> float:
    return 0.0 if x == 0 else x * math.log(y)


def kupiec_pof(n: int, x: int, p: float) -> tuple[float, float]:
    """Kupiec (1995) proportion-of-failures test.

    :math:`LR_{POF}=-2\\ln\\frac{(1-p)^{n-x}p^x}{(1-\\hat p)^{n-x}\\hat p^x}`, :math:`\\hat p=x/n`,
    asymptotically :math:`\\chi^2_1`. Returns ``(LR, p-value)``.
    """
    phat = x / n
    ll0 = _xlogy(n - x, 1 - p) + _xlogy(x, p)
    ll1 = _xlogy(n - x, 1 - phat) + _xlogy(x, phat)
    lr = max(0.0, -2.0 * (ll0 - ll1))
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen_independence(hits: np.ndarray) -> tuple[float, float, dict[str, int]]:
    """Christoffersen (1998) Markov independence test on the 0/1 exception sequence.

    With transition counts :math:`n_{ij}` (state i followed by j), :math:`\\pi_0=n_{01}/(n_{00}+n_{01})`,
    :math:`\\pi_1=n_{11}/(n_{10}+n_{11})`, :math:`\\pi=(n_{01}+n_{11})/\\sum n_{ij}`:
    :math:`LR_{ind}=-2\\ln\\frac{(1-\\pi)^{n_{00}+n_{10}}\\pi^{n_{01}+n_{11}}}
    {(1-\\pi_0)^{n_{00}}\\pi_0^{n_{01}}(1-\\pi_1)^{n_{10}}\\pi_1^{n_{11}}}\\sim\\chi^2_1`.
    Returns ``(LR, p-value, counts)``.
    """
    h = np.asarray(hits, dtype=int)
    a, b = h[:-1], h[1:]
    n00 = int(np.sum((a == 0) & (b == 0)))
    n01 = int(np.sum((a == 0) & (b == 1)))
    n10 = int(np.sum((a == 1) & (b == 0)))
    n11 = int(np.sum((a == 1) & (b == 1)))
    counts = {"n00": n00, "n01": n01, "n10": n10, "n11": n11}
    tot = n00 + n01 + n10 + n11
    if tot == 0:
        return 0.0, 1.0, counts
    pi = (n01 + n11) / tot
    pi0 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi1 = n11 / (n10 + n11) if n10 + n11 else 0.0
    ll0 = _xlogy(n00 + n10, 1 - pi) + _xlogy(n01 + n11, pi)
    ll1 = _xlogy(n00, 1 - pi0) + _xlogy(n01, pi0) + _xlogy(n10, 1 - pi1) + _xlogy(n11, pi1)
    lr = max(0.0, -2.0 * (ll0 - ll1))
    return lr, float(stats.chi2.sf(lr, 1)), counts


def basel_zone(x: int, n: int, p: float) -> tuple[str, float]:
    """Basel traffic light: binomial CDF :math:`F(x;n,p)` < 0.95 green, < 0.9999 yellow, else red."""
    cdf = float(stats.binom.cdf(x, n, p))
    zone = "green" if cdf < 0.95 else "yellow" if cdf < 0.9999 else "red"
    return zone, cdf


# --------------------------------------------------------------------------------------------
# Moving-block bootstrap
# --------------------------------------------------------------------------------------------


def block_length(n: int) -> int:
    """Block length :math:`\\ell=\\mathrm{round}(n^{1/3})` (at least 1)."""
    return max(1, int(round(n ** (1.0 / 3.0))))


def moving_block_indices(n: int, rng: np.random.Generator, length: int | None = None) -> np.ndarray:
    """Row indices of one moving-block bootstrap sample (Kunsch 1989): blocks of length l start uniformly
    in [0, n-l], are concatenated and truncated to n."""
    ell = block_length(n) if length is None else length
    nb = -(-n // ell)
    starts = rng.integers(0, n - ell + 1, size=nb)
    return (starts[:, None] + np.arange(ell)[None, :]).ravel()[:n]
