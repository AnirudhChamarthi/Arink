"""Benchmark B: historical market data (protocol section 4).

Run on a machine with internet access (downloads index levels with yfinance):

    python benchmarks/run_market.py

Or offline from CSV files named like ``GSPC.csv`` with columns ``Date,Close``:

    python benchmarks/run_market.py --csv-dir path/to/csvs

Raw prices are cached in ``benchmarks/data/`` (gitignored) and never committed; the results record
date ranges, observation counts and a hash of each series so a later run can confirm the snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import common
from models.backtest import basel_traffic_light, christoffersen_independence, kupiec_pof, rolling_var

SERIES = {
    "^GSPC": "S&P 500",
    "^GSPTSE": "S&P/TSX Composite",
    "^FTSE": "FTSE 100",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
}
START, END = "2000-01-01", "2025-12-31"
WINDOWS = {
    "full sample": (None, None),
    "GFC 2007-09": ("2007-07-01", "2009-06-30"),
    "COVID 2020": ("2020-02-01", "2020-06-30"),
    "Rates 2022": ("2022-01-01", "2022-12-31"),
}
METHODS = ("historical", "parametric", "ewma")
CONFIDENCES = (0.975, 0.99)
WINDOW = 250
BLOCK = 250
DATA_DIR = Path(__file__).resolve().parent / "data"


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "")


def fetch(ticker: str) -> pd.Series:
    import yfinance as yf

    end_exclusive = (pd.Timestamp(END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=START, end=end_exclusive, auto_adjust=True, progress=False)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.size < 1000:
        # yfinance reports failed downloads by returning an empty frame instead of raising.
        raise RuntimeError(f"Download of {ticker} returned {close.size} rows; check the connection and retry.")
    DATA_DIR.mkdir(exist_ok=True)
    close.rename("Close").to_csv(DATA_DIR / f"{safe_name(ticker)}.csv", index_label="Date")
    return close


def load_csv(directory: Path, ticker: str) -> pd.Series:
    df = pd.read_csv(directory / f"{safe_name(ticker)}.csv", parse_dates=["Date"])
    return df.set_index("Date")["Close"].dropna().sort_index()


def series_hash(close: pd.Series) -> str:
    blob = "\n".join(f"{d.date()},{v:.6f}" for d, v in close.items())
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def evaluate(close: pd.Series) -> list[dict]:
    """Rolling out-of-sample backtests for every method, confidence and window."""
    close = close.loc[START:END]
    rets = close.pct_change().dropna()
    r = rets.to_numpy()
    test_dates = rets.index[WINDOW:]
    losses = -r[WINDOW:]
    rows = []
    for c in CONFIDENCES:
        for m in METHODS:
            var = rolling_var(r, c, window=WINDOW, method=m)  # var[i] forecasts test_dates[i]
            for wname, (lo, hi) in WINDOWS.items():
                mask = np.ones(len(test_dates), dtype=bool)
                if lo:
                    mask &= test_dates >= pd.Timestamp(lo)
                if hi:
                    mask &= test_dates <= pd.Timestamp(hi)
                if mask.sum() < 20:
                    continue
                exc = losses[mask] > var[mask]
                n, k = int(exc.size), int(exc.sum())
                kup = kupiec_pof(k, n, c)
                ind = christoffersen_independence(exc)
                row = {
                    "window": wname, "method": m, "confidence": c, "days": n,
                    "exceptions": k, "expected": round(n * (1 - c), 2),
                    "exception_rate": k / n,
                    "kupiec_p": kup.p_value, "independence_p": ind.p_value,
                    # one-sided binomial p-value: probability of at least k exceptions
                    "binom_p_at_least": float(stats.binom.sf(k - 1, n, 1 - c)),
                }
                if c == 0.99 and wname == "full sample":
                    zones = [basel_traffic_light(int(exc[b:b + BLOCK].sum()), BLOCK, c)
                             for b in range(0, n - BLOCK + 1, BLOCK)]
                    row["basel_blocks"] = len(zones)
                    row["basel_yellow_or_red_share"] = sum(z != "green" for z in zones) / len(zones)
                    row["basel_red_share"] = zones.count("red") / len(zones)
                rows.append(row)
    return rows


def run(series: dict[str, pd.Series]) -> dict:
    out = {"series": []}
    for ticker, close in series.items():
        close = close.loc[START:END]
        out["series"].append({
            "ticker": ticker, "name": SERIES.get(ticker, ticker),
            "first_date": str(close.index[0].date()), "last_date": str(close.index[-1].date()),
            "observations": int(close.size), "data_sha256_16": series_hash(close),
            "rows": evaluate(close),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-dir", type=Path, default=None)
    args = ap.parse_args()
    series = {}
    for t in SERIES:
        series[t] = load_csv(args.csv_dir, t) if args.csv_dir else fetch(t)
    result = run(series)
    path = common.write_result("market", {
        "citable": args.csv_dir is None or len(series) == len(SERIES),
        "source": "csv" if args.csv_dir else "yfinance",
        "design": {"start": START, "end": END, "window": WINDOW, "methods": list(METHODS),
                   "confidences": list(CONFIDENCES), "windows": WINDOWS},
        **result,
    })
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
