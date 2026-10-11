"""Market data: yfinance prices, FRED risk-free rate, OpenFigi ISIN mapping, options chain."""

from __future__ import annotations

import json
import logging
import os
from datetime import date

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from data.cache import cache_get, cache_set
from schemas.contract import OptionsChain, OptionsStrike

logger = logging.getLogger(__name__)

_TRADING_DAYS = 252
_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


def _cache_key(prefix: str, *parts: str) -> str:
    return f"{prefix}:" + ":".join(p.upper() for p in parts)


def fetch_risk_free_rate() -> float:
    """3-month T-bill (TB3MS) from FRED public CSV export."""
    key = _cache_key("rf", "TB3MS")
    cached = cache_get(key)
    if cached is not None:
        return float(cached)
    rate = 0.045
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        lines = [ln for ln in resp.text.strip().splitlines() if ln and not ln.startswith("DATE")]
        if lines:
            last = lines[-1].split(",")
            if len(last) >= 2 and last[1] not in (".", ""):
                rate = float(last[1]) / 100.0
    except Exception as exc:
        logger.warning("FRED TB3MS fetch failed, using default: %s", exc)
    cache_set(key, rate)
    return rate


def resolve_ticker_from_isin(isin: str) -> str | None:
    if not isin:
        return None
    key = _cache_key("isin", isin)
    cached = cache_get(key)
    if cached is not None:
        return cached or None
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OPENFIGI_API_KEY")
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    payload = [{"idType": "ID_ISIN", "idValue": isin}]
    ticker = None
    try:
        resp = requests.post(_OPENFIGI_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and data[0].get("data"):
            ticker = data[0]["data"][0].get("ticker")
    except Exception as exc:
        logger.warning("OpenFigi lookup failed for %s: %s", isin, exc)
    cache_set(key, ticker or "")
    return ticker


def _log_returns(close: pd.Series) -> list[float]:
    prices = close.dropna()
    if len(prices) < 2:
        return [0.0] * _TRADING_DAYS
    rets = np.log(prices / prices.shift(1)).dropna()
    rets = rets.tail(_TRADING_DAYS)
    values = rets.tolist()
    if len(values) < _TRADING_DAYS:
        pad = [values[0] if values else 0.0] * (_TRADING_DAYS - len(values))
        values = pad + values
    return values[-_TRADING_DAYS:]


def _atm_implied_vol(ticker: str, spot: float) -> float:
    """30-day ATM implied vol from nearest expiry options chain."""
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            return 0.25
        chain = t.option_chain(expiries[0])
        calls = chain.calls
        if calls.empty or spot <= 0:
            return 0.25
        idx = (calls["strike"] - spot).abs().idxmin()
        iv = calls.loc[idx].get("impliedVolatility")
        if iv is None or (isinstance(iv, float) and np.isnan(iv)):
            return 0.25
        return float(iv)
    except Exception:
        return 0.25


def fetch_options_chain(ticker: str, spot: float) -> OptionsChain | None:
    key = _cache_key("optchain", ticker)
    cached = cache_get(key)
    if cached is not None:
        if cached == "":
            return None
        return OptionsChain.model_validate_json(cached)
    try:
        t = yf.Ticker(ticker)
        expiries = t.options[:2]
        if not expiries:
            cache_set(key, "")
            return None
        strikes: list[OptionsStrike] = []
        for exp in expiries:
            chain = t.option_chain(exp)
            exp_date = date.fromisoformat(exp)
            for _, row in chain.calls.iterrows():
                strike = float(row["strike"])
                if abs(strike - spot) / max(spot, 1e-6) > 0.15:
                    continue
                put_row = chain.puts[chain.puts["strike"] == strike]
                put_iv = float(put_row["impliedVolatility"].iloc[0]) if not put_row.empty else 0.25
                call_iv = float(row.get("impliedVolatility") or 0.25)
                strikes.append(
                    OptionsStrike(
                        strike=strike,
                        expiry=exp_date,
                        call_bid=float(row.get("bid") or 0),
                        call_ask=float(row.get("ask") or 0),
                        put_bid=float(put_row["bid"].iloc[0]) if not put_row.empty else 0,
                        put_ask=float(put_row["ask"].iloc[0]) if not put_row.empty else 0,
                        call_iv=call_iv,
                        put_iv=put_iv,
                        open_interest=int(row["openInterest"]) if pd.notna(row.get("openInterest")) else None,
                    )
                )
            if len(strikes) >= 12:
                break
        if not strikes:
            cache_set(key, "")
            return None
        result = OptionsChain(ticker=ticker.upper(), strikes=strikes[:24])
        cache_set(key, result.model_dump_json())
        return result
    except Exception as exc:
        logger.warning("Options chain fetch failed for %s: %s", ticker, exc)
        cache_set(key, "")
        return None


def fetch_ticker_market_data(ticker: str, risk_free_rate: float) -> dict:
    key = _cache_key("mkt", ticker)
    cached = cache_get(key)
    if cached is not None:
        return json.loads(cached) if isinstance(cached, str) else cached

    t = yf.Ticker(ticker)
    hist = t.history(period="1y", auto_adjust=True)
    info = t.info or {}
    if hist.empty:
        raise ValueError(f"No price history for ticker {ticker}")

    close = hist["Close"]
    current_price = float(close.iloc[-1])
    returns_252d = _log_returns(close)
    implied_vol = _atm_implied_vol(ticker, current_price)
    market_cap = info.get("marketCap")
    beta = info.get("beta")
    name = info.get("shortName") or info.get("longName") or ticker

    payload = {
        "name": name,
        "current_price": current_price,
        "returns_252d": returns_252d,
        "implied_vol": implied_vol,
        "risk_free_rate": risk_free_rate,
        "market_cap": float(market_cap) if market_cap else None,
        "beta": float(beta) if beta is not None else None,
    }
    cache_set(key, json.dumps(payload))
    return payload
