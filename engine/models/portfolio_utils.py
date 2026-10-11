"""Shared portfolio helpers for quant models.

Exposure conventions
--------------------
* ``position_signed_value``: market value with its sign. A short position (negative quantity)
  has a negative value, so it gains when the asset falls.
* ``gross_exposure``: sum of absolute market values. Risk percentages (VaR weights, stress P&L
  as a fraction of the portfolio) are expressed relative to gross exposure. For a long-only
  portfolio gross equals net, so results are identical to the previous long-only behaviour; for
  a long/short book it avoids dividing by a net value that can be close to zero.
* ``position_market_value`` / ``position_weights``: the *long book* only (shorts count as 0).
  Used by the ESG and carbon metrics, which describe what the portfolio owns.
"""

from __future__ import annotations

import numpy as np

from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def position_signed_value(pos: EnrichedPosition) -> float:
    """Signed market value; negative for short positions (and borrowed cash)."""
    if pos.asset_class == AssetClass.CASH:
        return float(pos.quantity)
    return float(pos.current_price * pos.quantity)


def position_market_value(pos: EnrichedPosition) -> float:
    """Long exposure only: shorts count as zero."""
    return max(position_signed_value(pos), 0.0)


def gross_exposure(portfolio: EnrichedPortfolio) -> float:
    return float(sum(abs(position_signed_value(p)) for p in portfolio.positions))


def position_weights(portfolio: EnrichedPortfolio) -> list[tuple[EnrichedPosition, float]]:
    """Long-book weights (shorts are 0). Used by the ESG / carbon metrics."""
    rows: list[tuple[EnrichedPosition, float]] = []
    for pos in portfolio.positions:
        rows.append((pos, position_market_value(pos)))
    total = sum(mv for _, mv in rows) or 1.0
    return [(pos, mv / total) for pos, mv in rows]


def returns_matrix(portfolio: EnrichedPortfolio, tickers: list[str]) -> np.ndarray:
    """Return an ``(n_days, n_assets)`` matrix of daily returns.

    Histories of different length (e.g. a recent listing) are aligned on their most recent days
    and truncated to the shortest available history, so every row is the same calendar day.
    Assets with no history (cash, say) contribute zeros.
    """
    by_ticker = {p.ticker.upper(): np.array(p.returns_252d, dtype=float) for p in portfolio.positions}
    series_list = [by_ticker.get(t.upper()) for t in tickers]
    lengths = [min(len(s), 252) for s in series_list if s is not None and len(s) > 0]
    n = min(lengths) if lengths else 252
    columns = []
    for series in series_list:
        if series is None or len(series) == 0:
            columns.append(np.zeros(n))
        else:
            columns.append(series[-n:])
    return np.column_stack(columns)


def weight_vector(portfolio: EnrichedPortfolio) -> tuple[list[str], np.ndarray]:
    """Signed weights relative to gross exposure (they sum to 1 for a long-only portfolio)."""
    tickers: list[str] = []
    values: list[float] = []
    for pos in portfolio.positions:
        tickers.append(pos.ticker.upper())
        values.append(position_signed_value(pos))
    gross = sum(abs(v) for v in values)
    if gross <= 0:
        n = len(values) or 1
        return tickers, np.ones(n) / n
    return tickers, np.array(values) / gross
