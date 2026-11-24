"""Dataset checks and the portfolio view (weights, cleaned return matrix) shared by the Q1 models."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import numpy as np

from riskbot.contract.errors import ValidationFailed
from riskbot.contract.types import MarketDataset


def as_market_dataset(dataset: Any, model_id: str) -> MarketDataset:
    """Accept a ``MarketDataset`` (or a dict that validates as one); otherwise raise ``ValidationFailed``."""
    if isinstance(dataset, MarketDataset):
        return dataset
    if isinstance(dataset, dict) and dataset.get("kind", "market") == "market":
        try:
            return MarketDataset.model_validate(dataset)
        except Exception as exc:  # pydantic.ValidationError
            raise ValidationFailed(f"{model_id}: invalid market dataset: {exc}", model_id=model_id) from exc
    kind = getattr(dataset, "kind", None) or (dataset.get("kind") if isinstance(dataset, dict) else None)
    raise ValidationFailed(f"{model_id} needs a market dataset, got kind={kind!r}", model_id=model_id,
                           expected="market", got=kind)


@dataclass
class Portfolio:
    """Signed weights and the listwise-cleaned return history of the non-cash holdings."""

    tickers: list[str]  # all positions, in dataset order (duplicates aggregated)
    market_values: np.ndarray  # signed MV per ticker
    weights: np.ndarray  # MV / gross, per ticker
    gross: float
    risky: list[str]  # non-cash tickers (have a return series)
    w_risky: np.ndarray  # weights of the risky tickers
    cash_weight: float
    R: np.ndarray  # (n_clean, k) returns of risky tickers, dates with any missing value removed
    dates: list[dt.date]  # dates of R rows
    dropped_dates: list[dt.date]  # dates removed for missing values
    missing_by_ticker: dict[str, int]


def build_portfolio(ds: MarketDataset, model_id: str) -> Portfolio:
    """Weights :math:`w_i = MV_i / \\sum_j |MV_j|` (cash MV = quantity) and listwise deletion of missing returns."""
    mv: dict[str, float] = {}
    cash: set[str] = set()
    for p in ds.positions:
        value = p.quantity if p.asset_class == "cash" else p.quantity * p.price
        mv[p.ticker] = mv.get(p.ticker, 0.0) + value
        if p.asset_class == "cash":
            cash.add(p.ticker)
    tickers = list(mv)
    mvs = np.array([mv[t] for t in tickers], dtype=float)
    gross = float(np.abs(mvs).sum())
    if not gross > 0:
        raise ValidationFailed(f"{model_id}: gross exposure is zero", model_id=model_id)
    weights = mvs / gross
    risky = [t for t in tickers if t not in cash]
    w_risky = np.array([weights[tickers.index(t)] for t in risky], dtype=float)
    cash_weight = float(sum(weights[tickers.index(t)] for t in cash))
    n = len(ds.dates)
    if risky:
        raw = np.array([[np.nan if v is None else float(v) for v in ds.returns[t]] for t in risky]).T
        raw = raw.reshape(n, len(risky))
    else:
        raw = np.zeros((n, 0))
    if not np.all(np.isfinite(raw[~np.isnan(raw)])):
        raise ValidationFailed(f"{model_id}: returns contain non-finite values", model_id=model_id)
    bad = np.isnan(raw).any(axis=1)
    missing_by_ticker = {t: int(np.isnan(raw[:, j]).sum()) for j, t in enumerate(risky) if np.isnan(raw[:, j]).any()}
    keep = ~bad
    dates = [d for d, k in zip(ds.dates, keep) if k]
    dropped = [d for d, k in zip(ds.dates, keep) if not k]
    return Portfolio(tickers, mvs, weights, gross, risky, w_risky, cash_weight, raw[keep], dates, dropped,
                     missing_by_ticker)
