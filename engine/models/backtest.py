"""VaR backtesting: exception counting, Kupiec POF, Christoffersen independence, Basel zones.

All functions are pure numpy/scipy and operate on a plain array of daily portfolio returns, so they
can be used on any return series (a single name, a weighted portfolio, a benchmark) without an
``EnrichedPortfolio``.

Conventions
-----------
* ``confidence`` is the VaR confidence level, e.g. 0.99.
* A *loss* is the negative of a return; an *exception* is a day whose loss exceeds that day's VaR.
* VaR is quoted as a positive number (a loss fraction), matching ``models.var``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats
from scipy.special import xlog1py, xlogy

BacktestMethod = Literal["historical", "parametric", "ewma"]

# Basel traffic-light boundaries on the cumulative binomial probability of the observed count.
_GREEN_CUM_PROB = 0.95
_RED_CUM_PROB = 0.9999


@dataclass(frozen=True)
class KupiecResult:
    n_obs: int
    n_exceptions: int
    expected_exceptions: float
    exception_rate: float
    lr_stat: float
    p_value: float
    reject: bool  # True -> reject "the model has correct coverage" at `alpha`


@dataclass(frozen=True)
class IndependenceResult:
    n01: int
    n11: int
    lr_stat: float
    p_value: float
    reject: bool  # True -> reject "exceptions are independent" at `alpha`


@dataclass(frozen=True)
class BacktestResult:
    method: str
    confidence: float
    window: int
    n_obs: int
    var_series: np.ndarray
    exceptions: np.ndarray
    kupiec: KupiecResult
    independence: IndependenceResult
    conditional_coverage_lr: float
    conditional_coverage_p_value: float
    traffic_light: str


def _log_bernoulli_likelihood(n_success: int, n_trials: int, prob: float) -> float:
    """``ln[(1-prob)^(n_trials-n_success) * prob^n_success]``, safe when prob is 0 or 1."""
    return float(xlog1py(n_trials - n_success, -prob) + xlogy(n_success, prob))


def kupiec_pof(
    n_exceptions: int,
    n_obs: int,
    confidence: float,
    alpha: float = 0.05,
) -> KupiecResult:
    """Kupiec proportion-of-failures (unconditional coverage) likelihood-ratio test.

    H0: the true exception probability equals ``p = 1 - confidence``.
    ``LR = -2 [ ln L(p) - ln L(N/T) ]`` is asymptotically chi-square with 1 degree of freedom.
    """
    if n_obs <= 0:
        raise ValueError("n_obs must be positive.")
    if not 0 <= n_exceptions <= n_obs:
        raise ValueError("n_exceptions must be between 0 and n_obs.")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1.")

    p = 1.0 - confidence
    observed = n_exceptions / n_obs
    lr = -2.0 * (
        _log_bernoulli_likelihood(n_exceptions, n_obs, p)
        - _log_bernoulli_likelihood(n_exceptions, n_obs, observed)
    )
    lr = max(lr, 0.0)  # guard tiny negative values from floating-point error
    p_value = float(stats.chi2.sf(lr, df=1))
    return KupiecResult(
        n_obs=n_obs,
        n_exceptions=n_exceptions,
        expected_exceptions=n_obs * p,
        exception_rate=observed,
        lr_stat=lr,
        p_value=p_value,
        reject=p_value < alpha,
    )


def christoffersen_independence(exceptions: np.ndarray, alpha: float = 0.05) -> IndependenceResult:
    """Christoffersen test that exceptions are serially independent (no clustering).

    Counts transitions between consecutive days: n_ij = days in state j following a day in state i,
    where 1 = exception. H0: P(exception | yesterday was one) = P(exception | yesterday was not).
    ``LR = -2 [ ln L(pi) - ln L(pi_01, pi_11) ]`` is chi-square with 1 degree of freedom.
    """
    ex = np.asarray(exceptions, dtype=bool)
    if ex.size < 2:
        raise ValueError("Need at least two observations for the independence test.")

    prev, curr = ex[:-1], ex[1:]
    n00 = int(np.sum(~prev & ~curr))
    n01 = int(np.sum(~prev & curr))
    n10 = int(np.sum(prev & ~curr))
    n11 = int(np.sum(prev & curr))

    total = n00 + n01 + n10 + n11
    pi = (n01 + n11) / total
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0

    ll_null = _log_bernoulli_likelihood(n01 + n11, total, pi)
    ll_alt = _log_bernoulli_likelihood(n01, n00 + n01, pi01) + _log_bernoulli_likelihood(
        n11, n10 + n11, pi11
    )
    lr = max(-2.0 * (ll_null - ll_alt), 0.0)
    p_value = float(stats.chi2.sf(lr, df=1))
    return IndependenceResult(n01=n01, n11=n11, lr_stat=lr, p_value=p_value, reject=p_value < alpha)


def basel_traffic_light(n_exceptions: int, n_obs: int, confidence: float) -> str:
    """Basel traffic-light zone from the cumulative binomial probability of the exception count.

    Green below 95%, yellow below 99.99%, red otherwise. For 250 observations at 99% this
    reproduces the published table: green 0-4, yellow 5-9, red 10+.
    """
    if n_obs <= 0:
        raise ValueError("n_obs must be positive.")
    cum_prob = float(stats.binom.cdf(n_exceptions, n_obs, 1.0 - confidence))
    if cum_prob < _GREEN_CUM_PROB:
        return "green"
    if cum_prob < _RED_CUM_PROB:
        return "yellow"
    return "red"


def rolling_var(
    returns: np.ndarray,
    confidence: float,
    window: int = 250,
    method: BacktestMethod = "historical",
    ewma_lambda: float = 0.94,
) -> np.ndarray:
    """One-day-ahead VaR forecasts for ``returns[window:]``, each using only earlier data.

    Entry ``i`` of the result is the forecast made from ``returns[i : i + window]`` for day
    ``i + window``.
    """
    r = np.asarray(returns, dtype=float)
    if window < 2 or r.size <= window:
        raise ValueError("Need more observations than the estimation window (and window >= 2).")

    z = stats.norm.ppf(confidence)
    out = np.empty(r.size - window)
    for i in range(out.size):
        hist = r[i : i + window]
        if method == "historical":
            out[i] = np.quantile(-hist, confidence)
        elif method == "parametric":
            out[i] = z * np.std(hist, ddof=1)
        elif method == "ewma":
            var = float(np.var(hist))
            for x in hist:
                var = ewma_lambda * var + (1.0 - ewma_lambda) * x * x
            out[i] = z * np.sqrt(var)
        else:
            raise ValueError(f"Unsupported backtest method: {method}")
    return out


def run_backtest(
    returns: np.ndarray,
    confidence: float = 0.99,
    window: int = 250,
    method: BacktestMethod = "historical",
    alpha: float = 0.05,
) -> BacktestResult:
    """Roll a VaR model over ``returns`` and test its exceptions."""
    r = np.asarray(returns, dtype=float)
    var_series = rolling_var(r, confidence, window, method)
    realised_losses = -r[window:]
    exceptions = realised_losses > var_series

    n_obs = int(exceptions.size)
    n_exc = int(exceptions.sum())
    kupiec = kupiec_pof(n_exc, n_obs, confidence, alpha)
    ind = christoffersen_independence(exceptions, alpha)

    cc_lr = kupiec.lr_stat + ind.lr_stat
    cc_p = float(stats.chi2.sf(cc_lr, df=2))
    return BacktestResult(
        method=method,
        confidence=confidence,
        window=window,
        n_obs=n_obs,
        var_series=var_series,
        exceptions=exceptions,
        kupiec=kupiec,
        independence=ind,
        conditional_coverage_lr=cc_lr,
        conditional_coverage_p_value=cc_p,
        traffic_light=basel_traffic_light(n_exc, n_obs, confidence),
    )
