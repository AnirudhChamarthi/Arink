"""Shared portfolio helpers for quant models."""

from __future__ import annotations

import numpy as np

from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def position_market_value(pos: EnrichedPosition) -> float:
    if pos.asset_class == AssetClass.CASH:
        return max(pos.quantity, 0.0)
    return max(pos.current_price * pos.quantity, 0.0)


def position_weights(portfolio: EnrichedPortfolio) -> list[tuple[EnrichedPosition, float]]:
    rows: list[tuple[EnrichedPosition, float]] = []
    for pos in portfolio.positions:
        rows.append((pos, position_market_value(pos)))
    total = sum(mv for _, mv in rows) or 1.0
    return [(pos, mv / total) for pos, mv in rows]


def returns_matrix(portfolio: EnrichedPortfolio, tickers: list[str]) -> np.ndarray:
    by_ticker = {p.ticker.upper(): np.array(p.returns_252d, dtype=float) for p in portfolio.positions}
    rows = []
    for ticker in tickers:
        series = by_ticker.get(ticker.upper())
        if series is None or len(series) == 0:
            rows.append(np.zeros(252))
        else:
            rows.append(series[-252:])
    return np.column_stack(rows)


def weight_vector(portfolio: EnrichedPortfolio) -> tuple[list[str], np.ndarray]:
    tickers: list[str] = []
    values: list[float] = []
    for pos in portfolio.positions:
        tickers.append(pos.ticker.upper())
        values.append(position_market_value(pos))
    total = sum(values)
    if total <= 0:
        n = len(values) or 1
        return tickers, np.ones(n) / n
    return tickers, np.array(values) / total
