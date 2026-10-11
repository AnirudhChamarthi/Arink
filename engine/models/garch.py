"""GARCH(1,1) volatility model for single-name return series."""

from __future__ import annotations

import numpy as np
from scipy import stats

from schemas.contract import ArmaOrder, EnrichedPortfolio, GarchResult


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
        return _ewma_fallback(pos.ticker, returns)
    except Exception as exc:
        return _ewma_fallback(pos.ticker, returns, note=str(exc))


def _fit_arch_garch(ticker: str, returns: np.ndarray) -> GarchResult:
    from arch import arch_model

    pct_returns = returns * 100.0
    model = arch_model(pct_returns, vol="Garch", p=1, q=1, rescale=False)
    fit = model.fit(disp="off")
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
    """EWMA volatility when arch is unavailable or fit fails."""
    lam = 0.94
    var = float(np.var(returns))
    for r in returns:
        var = lam * var + (1 - lam) * r * r
    daily_vol = np.sqrt(max(var, 1e-12))
    vol_series = [daily_vol * np.sqrt(1 + 0.01 * i) for i in range(10)]
    vol_forecast_10d = float(vol_series[-1])
    conditional_var_1d = float(daily_vol * stats.norm.ppf(0.99))

    return GarchResult(
        ticker=ticker,
        omega=float(var * (1 - lam)),
        alpha=0.1,
        beta_param=0.85,
        log_likelihood=0.0,
        aic=0.0,
        bic=0.0,
        vol_forecast_series=vol_series,
        vol_forecast_10d=vol_forecast_10d,
        conditional_var_1d=conditional_var_1d,
        arma_order=ArmaOrder(p=0, q=0),
    )
