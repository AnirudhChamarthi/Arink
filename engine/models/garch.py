"""GARCH(1,1) volatility model for single-name return series."""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy import stats

from schemas.contract import ArmaOrder, EnrichedPortfolio, GarchResult

logger = logging.getLogger(__name__)

EWMA_LAMBDA = 0.94


def run_garch(portfolio: EnrichedPortfolio, ticker: str) -> GarchResult:
    target = ticker.strip().upper()
    pos = next((p for p in portfolio.positions if p.ticker.upper() == target), None)
    if pos is None:
        raise ValueError(f"Ticker {ticker} not found in portfolio.")

    returns = np.array(pos.returns_252d, dtype=float)
    if len(returns) < 30:
        raise ValueError(f"Insufficient return history for {ticker} (need at least 30 days).")

    returns = returns[-252:]
    try:
        return _fit_arch_garch(pos.ticker, returns)
    except ImportError:
        logger.warning("GARCH for %s: 'arch' is not installed; using the EWMA fallback.", pos.ticker)
        return _ewma_fallback(pos.ticker, returns)
    except Exception as exc:
        logger.warning("GARCH for %s failed (%s); using the EWMA fallback.", pos.ticker, exc)
        return _ewma_fallback(pos.ticker, returns, note=str(exc))


def _fit_arch_garch(ticker: str, returns: np.ndarray) -> GarchResult:
    from arch import arch_model

    pct_returns = returns * 100.0
    model = arch_model(pct_returns, vol="Garch", p=1, q=1, rescale=False)
    fit = model.fit(disp="off")
    if fit.convergence_flag != 0:
        raise RuntimeError(f"optimizer did not converge (flag {fit.convergence_flag})")
    params = fit.params
    omega = float(params.get("omega", 0.0))
    alpha = float(params.get("alpha[1]", 0.0))
    beta = float(params.get("beta[1]", 0.0))
    forecast = fit.forecast(horizon=10, reindex=False)
    vol_series = np.sqrt(forecast.variance.values[-1]) / 100.0
    vol_forecast_10d = float(vol_series[-1])
    conditional_var_1d = float(vol_series[0] * stats.norm.ppf(0.99))

    return GarchResult(
        ticker=ticker,
        omega=omega,
        alpha=alpha,
        beta_param=beta,
        log_likelihood=float(fit.loglikelihood),
        aic=float(fit.aic),
        bic=float(fit.bic),
        vol_forecast_series=[float(v) for v in vol_series],
        vol_forecast_10d=vol_forecast_10d,
        conditional_var_1d=conditional_var_1d,
        arma_order=None,
    )


def _ewma_fallback(ticker: str, returns: np.ndarray, note: str = "") -> GarchResult:
    """RiskMetrics EWMA volatility, reported as the GARCH(1,1) it is a special case of.

    EWMA is GARCH(1,1) with omega = 0, alpha = 1 - lambda and beta = lambda, so those are the
    parameters reported (they used to be an unrelated 0.1 / 0.85). Because alpha + beta = 1 and
    omega = 0, the variance forecast is flat across horizons. The Gaussian log-likelihood is
    computed from the EWMA variance path; no parameters are estimated, so AIC = BIC = -2 * LL.
    ``arma_order`` is (0, 0) to mark this result as the fallback rather than a fitted model.
    """
    lam = EWMA_LAMBDA
    var = float(np.var(returns))
    var = max(var, 1e-12)
    log_lik = 0.0
    for r in returns:
        log_lik += -0.5 * (math.log(2 * math.pi) + math.log(var) + r * r / var)
        var = max(lam * var + (1 - lam) * r * r, 1e-12)

    daily_vol = math.sqrt(var)  # forecast for the next day, and (flat) for every day after
    vol_series = [daily_vol] * 10

    return GarchResult(
        ticker=ticker,
        omega=0.0,
        alpha=1.0 - lam,
        beta_param=lam,
        log_likelihood=float(log_lik),
        aic=float(-2.0 * log_lik),
        bic=float(-2.0 * log_lik),
        vol_forecast_series=vol_series,
        vol_forecast_10d=daily_vol,
        conditional_var_1d=float(daily_vol * stats.norm.ppf(0.99)),
        arma_order=ArmaOrder(p=0, q=0),
    )
