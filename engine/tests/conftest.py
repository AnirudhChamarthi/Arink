import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _synthetic_market_data(ticker: str, risk_free_rate: float) -> dict:
    """Deterministic per-ticker market data (stable across runs; ``hash()`` is not)."""
    seed = zlib.crc32(ticker.upper().encode("utf-8"))
    rng = np.random.default_rng(seed)
    return {
        "name": f"{ticker.upper()} (synthetic)",
        "current_price": 50.0 + float(seed % 200),
        "returns_252d": rng.normal(0.0003, 0.012, 252).tolist(),
        "implied_vol": 0.25,
        "risk_free_rate": risk_free_rate,
        "market_cap": 1.0e11,
        "beta": 1.1,
    }


@pytest.fixture(autouse=True)
def offline_market_data(request, monkeypatch):
    """Replace Yahoo / FRED / OpenFIGI lookups with synthetic data so tests run offline.

    Tests that genuinely need live data can opt out with ``@pytest.mark.live_market``.
    """
    if request.node.get_closest_marker("live_market"):
        return

    from data import market

    monkeypatch.setattr(market, "fetch_risk_free_rate", lambda: 0.045)
    monkeypatch.setattr(market, "fetch_ticker_market_data", _synthetic_market_data)
    monkeypatch.setattr(market, "fetch_options_chain", lambda ticker, spot: None)
    monkeypatch.setattr(market, "resolve_ticker_from_isin", lambda isin: None)
