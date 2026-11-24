"""Benchmark B runner, exercised offline on synthetic index levels."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_market  # noqa: E402
from models.backtest import rolling_var  # noqa: E402


def _fake_close(seed: int) -> pd.Series:
    dates = pd.bdate_range("1999-06-01", "2026-03-31")
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.01, dates.size)
    r[(dates >= "2008-09-01") & (dates <= "2008-12-31")] *= 4  # a crisis
    return pd.Series(100 * np.cumprod(1 + r), index=dates)


def test_csv_round_trip(tmp_path):
    close = _fake_close(1)
    close.rename("Close").to_csv(tmp_path / "GSPC.csv", index_label="Date")
    loaded = run_market.load_csv(tmp_path, "^GSPC")
    assert loaded.index[0] == close.index[0] and loaded.size == close.size
    assert run_market.series_hash(loaded) == run_market.series_hash(close.round(6))


def test_evaluation_respects_the_fixed_sample_and_windows():
    out = run_market.run({"^GSPC": _fake_close(2)})
    s = out["series"][0]
    assert s["first_date"] >= "2000-01-01" and s["last_date"] <= "2025-12-31"
    windows = {r["window"] for r in s["rows"]}
    assert windows == set(run_market.WINDOWS)
    full = [r for r in s["rows"] if r["window"] == "full sample" and r["confidence"] == 0.99]
    assert len(full) == 3 and all("basel_blocks" in r for r in full)


def test_crisis_window_exceptions_match_a_direct_recount():
    close = _fake_close(3).loc[run_market.START:run_market.END]
    rets = close.pct_change().dropna()
    r = rets.to_numpy()
    var = rolling_var(r, 0.99, 250, "parametric")
    dates = rets.index[250:]
    mask = (dates >= "2007-07-01") & (dates <= "2009-06-30")
    expected = int((-r[250:][mask] > var[mask]).sum())
    rows = run_market.evaluate(close)
    row = next(x for x in rows if x["window"] == "GFC 2007-09" and x["method"] == "parametric"
               and x["confidence"] == 0.99)
    assert row["exceptions"] == expected
    assert row["exceptions"] > row["expected"]  # the injected crisis must show up


def test_correct_model_on_iid_data_is_mostly_green():
    rows = run_market.evaluate(_fake_close(4).loc[run_market.START:run_market.END])
    full = next(x for x in rows if x["window"] == "full sample" and x["method"] == "parametric"
                and x["confidence"] == 0.975)
    assert full["exception_rate"] == pytest.approx(0.025, abs=0.006)
