"""Risk modes: optimistic / normal / cautious presets for the parametric risk maths.

A mode does not change *what* is measured, only *how conservative the assumptions are*. Each mode
is a small bundle of parameters (a ``RiskProfile``); every parameter maps to one specific term in
the formulas below, so the effect of a mode can always be traced back to the maths.

Parametric VaR and expected shortfall (ES) for portfolio weights ``w``::

    sigma_p = sqrt(w' Sigma w)                      # daily portfolio volatility
    VaR_c   = q_c  * sigma_p * sqrt(h)              # q_c: quantile multiplier
    ES_c    = e_c  * sigma_p * sqrt(h)              # e_c: tail-average multiplier

What a mode changes:

1. ``vol_estimator`` -> how ``Sigma`` is estimated
     sample : equal-weighted sample covariance over the whole window (slow to react)
     ewma   : RiskMetrics recursion S_t = lam*S_{t-1} + (1-lam)*r_t r_t'   (reacts to recent shocks)
     min    : per-asset min(sample vol, EWMA vol), EWMA correlations (the calmer of the two views)
     max    : per-asset max(sample vol, EWMA vol), EWMA correlations (the harsher of the two views)
   The presets use min / ewma / max, which guarantees optimistic <= normal <= cautious for
   volatility whatever the recent regime (given non-negative correlations).
2. ``corr_stress`` (k in [0, 1]) -> correlations pulled toward 1:  R' = (1-k) R + k 11'
     Diversification shrinks in crises, so a cautious mode removes some of it.
3. ``tail_dof`` (nu) -> Student-t tails instead of normal (None = normal)
     q_c = t_nu^-1(c) * sqrt((nu-2)/nu)      (scaled to unit variance, so only the tail shape changes)
     e_c = f_nu(t) / (1-c) * (nu + t^2)/(nu-1) * sqrt((nu-2)/nu),  t = t_nu^-1(c)
4. ``stress_multiplier`` (m) -> scenario severity: losses x m, gains x 1/m (capped at -100%)
5. ``carbon_price`` -> the $/tCO2e shock used by the carbon-VaR calculation
6. ``confidence`` -> default confidence level (callers can override it)

Nothing here replaces ``models.var``; it is an additional, opt-in layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy import stats

from models.portfolio_utils import returns_matrix, weight_vector
from models.stress import _load_scenarios, run_stress
from models.sustainability import run_sustainability
from schemas.contract import (
    EnrichedPortfolio,
    StressResult,
    StressScenario,
    SustainabilityResult,
)


class RiskMode(str, Enum):
    OPTIMISTIC = "optimistic"
    NORMAL = "normal"
    CAUTIOUS = "cautious"


class VolEstimator(str, Enum):
    SAMPLE = "sample"
    EWMA = "ewma"
    MIN_OF_BOTH = "min"
    MAX_OF_BOTH = "max"


@dataclass(frozen=True)
class RiskProfile:
    mode: RiskMode
    confidence: float
    vol_estimator: VolEstimator
    corr_stress: float
    tail_dof: float | None
    stress_multiplier: float
    carbon_price: float
    ewma_lambda: float = 0.94

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence < 1.0:
            raise ValueError("confidence must be strictly between 0 and 1.")
        if not 0.0 <= self.corr_stress <= 1.0:
            raise ValueError("corr_stress must be between 0 and 1.")
        if self.tail_dof is not None and self.tail_dof <= 2.0:
            raise ValueError("tail_dof must be greater than 2 (finite variance) or None.")
        if self.stress_multiplier <= 0.0:
            raise ValueError("stress_multiplier must be positive.")
        if not 0.0 < self.ewma_lambda < 1.0:
            raise ValueError("ewma_lambda must be strictly between 0 and 1.")
        if self.carbon_price < 0.0:
            raise ValueError("carbon_price must be non-negative.")


PROFILES: dict[RiskMode, RiskProfile] = {
    RiskMode.OPTIMISTIC: RiskProfile(
        mode=RiskMode.OPTIMISTIC,
        confidence=0.95,
        vol_estimator=VolEstimator.MIN_OF_BOTH,
        corr_stress=0.0,
        tail_dof=None,
        stress_multiplier=0.75,
        carbon_price=25.0,
    ),
    RiskMode.NORMAL: RiskProfile(
        mode=RiskMode.NORMAL,
        confidence=0.99,
        vol_estimator=VolEstimator.EWMA,
        corr_stress=0.0,
        tail_dof=None,
        stress_multiplier=1.0,
        carbon_price=50.0,  # matches the existing run_sustainability default
    ),
    RiskMode.CAUTIOUS: RiskProfile(
        mode=RiskMode.CAUTIOUS,
        confidence=0.995,
        vol_estimator=VolEstimator.MAX_OF_BOTH,
        corr_stress=0.30,
        tail_dof=5.0,
        stress_multiplier=1.5,
        carbon_price=100.0,
    ),
}


def get_profile(mode: RiskMode | str) -> RiskProfile:
    return PROFILES[RiskMode(mode)]


@dataclass(frozen=True)
class ModeVarResult:
    mode: RiskMode
    confidence: float
    horizon_days: int
    var: float
    es: float
    portfolio_vol_daily: float
    quantile_multiplier: float  # q_c: VaR / (sigma_p * sqrt(h))
    es_multiplier: float  # e_c: ES  / (sigma_p * sqrt(h))


# ----------------------------- covariance building blocks -----------------------------


def sample_covariance(returns: np.ndarray) -> np.ndarray:
    return np.atleast_2d(np.cov(returns, rowvar=False))


def ewma_covariance(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """RiskMetrics EWMA covariance. ``returns`` is (days, assets), oldest row first.

    Seeded with the sample covariance; each day then updates ``S = lam*S + (1-lam) r r'``.
    """
    s = sample_covariance(returns)
    for row in returns:
        s = lam * s + (1.0 - lam) * np.outer(row, row)
    return s


def _vols_and_correlation(cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vols = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    denom = np.outer(vols, vols)
    corr = np.divide(cov, denom, out=np.zeros_like(cov, dtype=float), where=denom > 0)
    np.fill_diagonal(corr, 1.0)
    return vols, corr


def stress_correlation(corr: np.ndarray, k: float) -> np.ndarray:
    """Blend a correlation matrix toward all-ones: ``(1-k) R + k 11'``.

    A convex combination of two positive semi-definite matrices with unit diagonal, so the result
    is a valid correlation matrix. ``k=0`` leaves ``R`` unchanged; ``k=1`` makes every pair
    perfectly correlated (no diversification).
    """
    return (1.0 - k) * corr + k * np.ones_like(corr)


def profile_covariance(returns: np.ndarray, profile: RiskProfile) -> np.ndarray:
    sample = sample_covariance(returns)
    if profile.vol_estimator == VolEstimator.SAMPLE:
        cov = sample
    elif profile.vol_estimator == VolEstimator.EWMA:
        cov = ewma_covariance(returns, profile.ewma_lambda)
    else:
        # MIN_OF_BOTH / MAX_OF_BOTH: per-asset volatility is the calmer / the harsher of the
        # long-run (sample) and recent (EWMA) estimates, combined with the EWMA correlations.
        ewma = ewma_covariance(returns, profile.ewma_lambda)
        pick = np.minimum if profile.vol_estimator == VolEstimator.MIN_OF_BOTH else np.maximum
        vols = pick(np.sqrt(np.diag(sample)), np.sqrt(np.diag(ewma)))
        _, corr = _vols_and_correlation(ewma)
        cov = np.outer(vols, vols) * corr

    if profile.corr_stress > 0.0:
        vols, corr = _vols_and_correlation(cov)
        cov = np.outer(vols, vols) * stress_correlation(corr, profile.corr_stress)
    return cov


# ----------------------------- tail multipliers -----------------------------


def var_quantile(confidence: float, dof: float | None) -> float:
    """VaR multiplier ``q_c`` for a unit-variance loss distribution (normal or scaled Student-t)."""
    if dof is None:
        return float(stats.norm.ppf(confidence))
    return float(stats.t.ppf(confidence, dof) * np.sqrt((dof - 2.0) / dof))


def es_multiplier(confidence: float, dof: float | None) -> float:
    """Expected-shortfall multiplier ``e_c`` for a unit-variance loss distribution."""
    if dof is None:
        z = stats.norm.ppf(confidence)
        return float(stats.norm.pdf(z) / (1.0 - confidence))
    t = stats.t.ppf(confidence, dof)
    raw = stats.t.pdf(t, dof) / (1.0 - confidence) * (dof + t * t) / (dof - 1.0)
    return float(raw * np.sqrt((dof - 2.0) / dof))


# ----------------------------- public API -----------------------------


def moded_parametric_var(
    portfolio: EnrichedPortfolio,
    mode: RiskMode | str = RiskMode.NORMAL,
    horizon_days: int = 1,
    confidence: float | None = None,
    profile: RiskProfile | None = None,
) -> ModeVarResult:
    """Parametric VaR and ES under a risk mode.

    ``confidence`` overrides the mode's default level (useful to compare modes at the same level).
    ``profile`` lets callers pass a tweaked profile instead of a preset.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1.")
    prof = profile or get_profile(mode)
    c = prof.confidence if confidence is None else confidence
    if not 0.0 < c < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1.")

    tickers, weights = weight_vector(portfolio)
    if not tickers:
        return ModeVarResult(prof.mode, c, horizon_days, 0.0, 0.0, 0.0, 0.0, 0.0)

    cov = profile_covariance(returns_matrix(portfolio, tickers), prof)
    sigma_p = float(np.sqrt(max(weights @ cov @ weights, 0.0)))
    scale = sigma_p * np.sqrt(horizon_days)
    q = var_quantile(c, prof.tail_dof)
    e = es_multiplier(c, prof.tail_dof)
    return ModeVarResult(
        mode=prof.mode,
        confidence=c,
        horizon_days=horizon_days,
        var=float(q * scale),
        es=float(e * scale),
        portfolio_vol_daily=sigma_p,
        quantile_multiplier=q,
        es_multiplier=e,
    )


def scaled_shocks(shocks: dict[str, float], multiplier: float) -> dict[str, float]:
    """Make a scenario more (m > 1) or less (m < 1) severe.

    Losses are multiplied by ``m`` (floored at -100%); gains are divided by ``m``, so a cautious
    mode does not count on offsetting gains growing alongside the losses.
    """
    if multiplier <= 0.0:
        raise ValueError("multiplier must be positive.")
    out: dict[str, float] = {}
    for key, value in shocks.items():
        v = float(value)
        out[key] = max(-1.0, v * multiplier) if v < 0.0 else v / multiplier
    return out


def run_stress_with_mode(
    portfolio: EnrichedPortfolio,
    scenario: StressScenario,
    mode: RiskMode | str = RiskMode.NORMAL,
    custom_shocks: dict[str, float] | None = None,
    profile: RiskProfile | None = None,
) -> StressResult:
    """``run_stress`` with the scenario's shocks rescaled by the mode's severity multiplier."""
    prof = profile or get_profile(mode)
    if scenario == StressScenario.CUSTOM:
        base = dict(custom_shocks or {})
        if not base:
            raise ValueError("custom scenario requires custom_shocks.")
    else:
        entry = _load_scenarios().get(scenario.value)
        if entry is None:
            raise ValueError(f"Unknown stress scenario: {scenario.value}")
        base = dict(entry.get("shocks") or {})

    result = run_stress(
        portfolio,
        StressScenario.CUSTOM,
        scaled_shocks(base, prof.stress_multiplier),
    )
    return result.model_copy(update={"scenario": scenario.value})


def run_sustainability_with_mode(
    portfolio: EnrichedPortfolio,
    mode: RiskMode | str = RiskMode.NORMAL,
    exclusion_filters: list[str] | None = None,
    profile: RiskProfile | None = None,
) -> SustainabilityResult:
    """``run_sustainability`` using the mode's carbon-price shock."""
    prof = profile or get_profile(mode)
    return run_sustainability(
        portfolio, exclusion_filters, carbon_price_shock=prof.carbon_price
    )


__all__ = [
    "ModeVarResult",
    "PROFILES",
    "RiskMode",
    "RiskProfile",
    "VolEstimator",
    "es_multiplier",
    "ewma_covariance",
    "get_profile",
    "moded_parametric_var",
    "profile_covariance",
    "run_stress_with_mode",
    "run_sustainability_with_mode",
    "sample_covariance",
    "scaled_shocks",
    "stress_correlation",
    "var_quantile",
]
