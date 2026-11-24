"""Deterministic synthetic market book for Q1 (``synthetic=True``).

Design (CONTRACT.md section 7)
------------------------------
* 14 positions: 13 equities in 9 sectors (3 shorts) and one USD cash line; gross exposure about 10m.
* 780 business days ending 2026-10-30.
* One-factor model with a common GARCH(1,1) volatility and Student-t(5) shocks:
  :math:`r_{it}=\\mu_i+\\sigma_i m_t h_t\\,(s_i\\varepsilon^{M}_t+\\sqrt{1-s_i^2}\\,\\varepsilon^{i}_t)`, where the
  :math:`\\varepsilon` are independent standardised t(5) shocks and
  :math:`h_t^2=\\omega+\\alpha h_{t-1}^2(\\varepsilon^M_{t-1})^2+\\beta h_{t-1}^2` is a unit-variance GARCH(1,1)
  (:math:`\\alpha=0.08,\\ \\beta=0.90`) driven by the market shock. Conditional correlations are
  :math:`s_is_j` with :math:`s_i\\in[0.50,0.77]`, i.e. about 0.25-0.6.
* Stress episode: :math:`m_t=3` on 60 days starting at day 150 (inside the oldest 500 days, so it is in the
  750-day window but not the 250-day window); :math:`m_t=1` otherwise.
* Data-quality defects: 6 missing returns in HTLX and a run of 7 zero returns in KILO (both in the last
  250 days).
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from riskbot.contract.types import MarketDataset, MarketPosition

N_DAYS = 780
END = dt.date(2026, 10, 30)
STRESS_START, STRESS_LEN, STRESS_MULT = 150, 60, 3.0
T_DOF = 5.0
G_ALPHA, G_BETA = 0.08, 0.90

# ticker, sector, target market value (signed), price, daily vol, factor loading s_i
_BOOK = [
    ("ALFA", "technology", 1_200_000, 182.40, 0.021, 0.74),
    ("BRVO", "technology", 900_000, 64.15, 0.024, 0.70),
    ("CHRL", "financials", 850_000, 48.90, 0.017, 0.68),
    ("DLTA", "financials", -600_000, 31.25, 0.019, 0.66),
    ("ECHO", "energy", 800_000, 77.80, 0.022, 0.55),
    ("FXTR", "energy", 550_000, 22.35, 0.025, 0.50),
    ("GOLF", "healthcare", 950_000, 141.10, 0.014, 0.52),
    ("HTLX", "healthcare", 600_000, 56.70, 0.018, 0.52),
    ("INDG", "industrials", 750_000, 95.60, 0.016, 0.72),
    ("JUNO", "consumer_staples", 700_000, 39.80, 0.012, 0.50),
    ("KILO", "utilities", 650_000, 28.45, 0.013, 0.50),
    ("LIMA", "consumer_discretionary", -700_000, 118.30, 0.023, 0.77),
    ("MIKE", "materials", -450_000, 44.05, 0.020, 0.60),
]
CASH = ("USD_CASH", 500_000.0)
MISSING_TICKER, MISSING_DAYS = "HTLX", [560, 601, 602, 655, 700, 742]
STALE_TICKER, STALE_START, STALE_LEN = "KILO", 610, 7


def _common_vol(rng: np.random.Generator, n: int, burn: int = 500) -> tuple[np.ndarray, np.ndarray]:
    """Market shocks and the unit-variance GARCH(1,1) volatility path they drive."""
    omega = 1.0 - G_ALPHA - G_BETA
    eps = rng.standard_t(T_DOF, size=n + burn) / math.sqrt(T_DOF / (T_DOF - 2.0))
    h = np.empty(n + burn)
    s2 = 1.0
    prev = 0.0
    for t in range(n + burn):
        s2 = omega + G_ALPHA * prev**2 + G_BETA * s2
        h[t] = math.sqrt(s2)
        prev = h[t] * eps[t]
    return eps[burn:], h[burn:]


def sample_dataset(seed: int = 0) -> MarketDataset:
    """Build the synthetic Q1 book; identical output for the same ``seed``."""
    rng = np.random.default_rng(seed)
    dates = [d.date() for d in pd.bdate_range(end=pd.Timestamp(END), periods=N_DAYS)]
    mult = np.ones(N_DAYS)
    mult[STRESS_START:STRESS_START + STRESS_LEN] = STRESS_MULT
    eps_m, h = _common_vol(rng, N_DAYS)
    positions: list[MarketPosition] = []
    returns: dict[str, list[float | None]] = {}
    for ticker, sector, mv, price, vol, s in _BOOK:
        eps_i = rng.standard_t(T_DOF, size=N_DAYS) / math.sqrt(T_DOF / (T_DOF - 2.0))
        drift = 0.0002 * (1.0 if mv > 0 else 0.5)
        r = drift + vol * mult * h * (s * eps_m + math.sqrt(1.0 - s * s) * eps_i)
        r = np.maximum(r, -0.95)
        series: list[float | None] = [round(float(v), 8) for v in r]
        if ticker == MISSING_TICKER:
            for i in MISSING_DAYS:
                series[i] = None
        if ticker == STALE_TICKER:
            for i in range(STALE_START, STALE_START + STALE_LEN):
                series[i] = 0.0
        returns[ticker] = series
        qty = float(round(mv / price))
        positions.append(MarketPosition(ticker=ticker, asset_class="equity", sector=sector, quantity=qty, price=price))
    positions.append(MarketPosition(ticker=CASH[0], asset_class="cash", sector=None, quantity=CASH[1], price=1.0))
    return MarketDataset(
        name="Synthetic long/short equity book (Q1 sample)",
        base_currency="USD",
        as_of=END,
        synthetic=True,
        positions=positions,
        dates=dates,
        returns=returns,
    )
