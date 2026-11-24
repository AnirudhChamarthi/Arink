"""Data-generating processes with a known true conditional VaR (protocol section 3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

BURN_IN = 500
WINDOW = 250
TEST_DAYS = 1000
SEED_ROOT = 20261123

GARCH_OMEGA, GARCH_ALPHA, GARCH_BETA = 2e-6, 0.08, 0.90
T_NU = 5


@dataclass(frozen=True)
class Path:
    returns: np.ndarray  # length WINDOW + TEST_DAYS (burn-in removed)
    sigma: np.ndarray  # true conditional volatility for each day, same length
    innovation: str  # "normal" or "t5"

    def true_var(self, confidence: float) -> np.ndarray:
        """True one-day loss quantile for every day (positive number)."""
        return self.sigma * innovation_quantile(self.innovation, confidence)


def innovation_quantile(innovation: str, confidence: float) -> float:
    if innovation == "normal":
        return float(stats.norm.ppf(confidence))
    if innovation == "t5":
        return float(stats.t.ppf(confidence, T_NU) * np.sqrt((T_NU - 2) / T_NU))
    raise ValueError(innovation)


def _innovations(rng: np.random.Generator, kind: str, n: int) -> np.ndarray:
    if kind == "normal":
        return rng.standard_normal(n)
    return rng.standard_t(T_NU, n) * np.sqrt((T_NU - 2) / T_NU)  # unit variance


def _garch(rng: np.random.Generator, kind: str) -> Path:
    n = BURN_IN + WINDOW + TEST_DAYS
    eps = _innovations(rng, kind, n)
    r = np.empty(n)
    sig = np.empty(n)
    h = GARCH_OMEGA / (1.0 - GARCH_ALPHA - GARCH_BETA)
    for t in range(n):
        sig[t] = np.sqrt(h)
        r[t] = sig[t] * eps[t]
        h = GARCH_OMEGA + GARCH_ALPHA * r[t] ** 2 + GARCH_BETA * h
    return Path(r[BURN_IN:], sig[BURN_IN:], kind)


def _normal_iid(rng: np.random.Generator) -> Path:
    n = WINDOW + TEST_DAYS
    sig = np.full(n, 0.01)
    return Path(sig * rng.standard_normal(BURN_IN + n)[BURN_IN:], sig, "normal")


def _regime_stress(rng: np.random.Generator) -> Path:
    n = WINDOW + TEST_DAYS
    sig = np.full(n, 0.008)
    sig[WINDOW + 400 : WINDOW + 525] = 0.024
    return Path(sig * rng.standard_normal(BURN_IN + n)[BURN_IN:], sig, "normal")


DGPS = {
    "normal_iid": lambda rng: _normal_iid(rng),
    "garch_normal": lambda rng: _garch(rng, "normal"),
    "garch_t5": lambda rng: _garch(rng, "t5"),
    "regime_stress": lambda rng: _regime_stress(rng),
}
DGP_INDEX = {name: i for i, name in enumerate(DGPS)}


def simulate(dgp: str, path_index: int) -> Path:
    rng = np.random.default_rng([SEED_ROOT, DGP_INDEX[dgp], path_index])
    return DGPS[dgp](rng)
