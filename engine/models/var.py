"""Parametric, historical, and Monte Carlo VaR and CVaR."""

from __future__ import annotations

import numpy as np
from scipy import stats

from models.portfolio_utils import returns_matrix, weight_vector
from schemas.contract import EnrichedPortfolio, VarContribution, VarMethod, VarResult


def parametric_var(
    portfolio: EnrichedPortfolio,
    confidence: float,
    horizon_days: int,
) -> VarResult:
    tickers, weights = weight_vector(portfolio)
    if not tickers:
        return _empty_result(confidence, horizon_days, VarMethod.PARAMETRIC)

    R = returns_matrix(portfolio, tickers)
    cov = np.cov(R, rowvar=False)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    port_var_daily = float(weights @ cov @ weights)
    port_vol_daily = np.sqrt(max(port_var_daily, 0.0))

    z = stats.norm.ppf(confidence)
    horizon_scale = np.sqrt(horizon_days)
    var_decimal = float(z * port_vol_daily * horizon_scale)
    cvar_decimal = float(
        port_vol_daily * horizon_scale * stats.norm.pdf(z) / (1.0 - confidence)
    )

    contributions = _component_contributions(tickers, weights, cov, var_decimal)
    return VarResult(
        var=var_decimal,
        cvar=cvar_decimal,
        method=VarMethod.PARAMETRIC,
        confidence=confidence,
        horizon_days=horizon_days,
        contributions=contributions,
    )


def historical_var(
    portfolio: EnrichedPortfolio,
    confidence: float,
    horizon_days: int,
) -> VarResult:
    tickers, weights = weight_vector(portfolio)
    if not tickers:
        return _empty_result(confidence, horizon_days, VarMethod.HISTORICAL)

    R = returns_matrix(portfolio, tickers)
    port_returns = R @ weights
    if horizon_days > 1:
        port_returns = np.array(
            [
                np.sum(port_returns[max(0, i - horizon_days + 1) : i + 1])
                for i in range(len(port_returns))
            ]
        )

    losses = -port_returns
    var_decimal = float(np.quantile(losses, confidence))
    tail = losses[losses >= var_decimal]
    cvar_decimal = float(np.mean(tail)) if len(tail) else var_decimal

    contributions = _historical_contributions(portfolio, tickers, weights, var_decimal, horizon_days)
    return VarResult(
        var=max(var_decimal, 0.0),
        cvar=max(cvar_decimal, 0.0),
        method=VarMethod.HISTORICAL,
        confidence=confidence,
        horizon_days=horizon_days,
        contributions=contributions,
    )


def montecarlo_var(
    portfolio: EnrichedPortfolio,
    confidence: float,
    horizon_days: int,
    n_sims: int = 10000,
) -> VarResult:
    tickers, weights = weight_vector(portfolio)
    if not tickers:
        return _empty_result(confidence, horizon_days, VarMethod.MONTECARLO)

    R = returns_matrix(portfolio, tickers)
    cov = np.cov(R, rowvar=False)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    mean = np.mean(R, axis=0)
    rng = np.random.default_rng(42)
    # h-day return of iid daily returns ~ N(h * mu, h * Sigma): the drift grows linearly in h and
    # the volatility with sqrt(h). (Scaling the whole draw by sqrt(h) wrongly scaled the drift too.)
    sims = rng.multivariate_normal(mean * horizon_days, cov * horizon_days, size=n_sims) @ weights

    losses = -sims
    var_decimal = float(np.quantile(losses, confidence))
    tail = losses[losses >= var_decimal]
    cvar_decimal = float(np.mean(tail)) if len(tail) else var_decimal

    ci_low = float(np.quantile(losses, max(0.0, confidence - 0.025)))
    ci_high = float(np.quantile(losses, min(1.0, confidence + 0.025)))

    contributions = _component_contributions(tickers, weights, cov, var_decimal)
    return VarResult(
        var=max(var_decimal, 0.0),
        cvar=max(cvar_decimal, 0.0),
        method=VarMethod.MONTECARLO,
        confidence=confidence,
        horizon_days=horizon_days,
        contributions=contributions,
        confidence_interval_low=ci_low,
        confidence_interval_high=ci_high,
    )


def run_var(
    portfolio: EnrichedPortfolio,
    method: VarMethod,
    confidence: float,
    horizon_days: int,
    n_sims: int = 10000,
) -> VarResult:
    if method == VarMethod.PARAMETRIC:
        return parametric_var(portfolio, confidence, horizon_days)
    if method == VarMethod.HISTORICAL:
        return historical_var(portfolio, confidence, horizon_days)
    if method == VarMethod.MONTECARLO:
        return montecarlo_var(portfolio, confidence, horizon_days, n_sims)
    raise ValueError(f"Unsupported VaR method: {method.value}")


def _empty_result(confidence: float, horizon_days: int, method: VarMethod) -> VarResult:
    return VarResult(
        var=0.0,
        cvar=0.0,
        method=method,
        confidence=confidence,
        horizon_days=horizon_days,
        contributions=[],
    )


def _component_contributions(
    tickers: list[str],
    weights: np.ndarray,
    cov: np.ndarray,
    var_decimal: float,
) -> list[VarContribution]:
    marginal = cov @ weights
    component = weights * marginal
    total_component = float(np.sum(component))
    contributions: list[VarContribution] = []
    for i, ticker in enumerate(tickers):
        if total_component > 1e-12:
            contrib = float(component[i] / total_component * var_decimal)
            pct = float(component[i] / total_component)
        else:
            contrib = 0.0
            pct = 0.0
        contributions.append(
            VarContribution(ticker=ticker, var_contribution=contrib, pct_of_total=pct)
        )
    return contributions


def _historical_contributions(
    portfolio: EnrichedPortfolio,
    tickers: list[str],
    weights: np.ndarray,
    var_decimal: float,
    horizon_days: int,
) -> list[VarContribution]:
    R = returns_matrix(portfolio, tickers)
    position_losses = -R
    if horizon_days > 1:
        position_losses = position_losses * np.sqrt(horizon_days)
    marginal = np.mean(position_losses, axis=0) * weights
    total = float(np.sum(np.abs(marginal))) or 1.0
    contributions: list[VarContribution] = []
    for i, ticker in enumerate(tickers):
        pct = float(abs(marginal[i]) / total)
        contributions.append(
            VarContribution(
                ticker=ticker,
                var_contribution=pct * var_decimal,
                pct_of_total=pct,
            )
        )
    return contributions
