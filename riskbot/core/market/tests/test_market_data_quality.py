"""q1.data_quality: detection of injected defects and the quality label."""

import datetime as dt

import numpy as np
import pytest

from riskbot.contract import catalog
from riskbot.contract.conformance import check_output
from riskbot.contract.types import MarketDataset, MarketPosition
from riskbot.core.market import sample_dataset
from riskbot.core.market.data_quality import DataQualityModel, longest_zero_run, outlier_mask


def _ds(series: dict[str, list], cash=True):
    n = len(next(iter(series.values())))
    dates = [dt.date(2022, 1, 3) + dt.timedelta(days=i) for i in range(n)]
    pos = [MarketPosition(ticker=t, quantity=10, price=5.0) for t in series]
    if cash:
        pos.append(MarketPosition(ticker="CASH", asset_class="cash", quantity=100, price=1.0))
    return MarketDataset(name="dq", as_of=dates[-1], synthetic=True, positions=pos, dates=dates, returns=series)


def _clean(n=400, k=3, seed=0):
    rng = np.random.default_rng(seed)
    return {f"S{i}": [float(v) for v in rng.normal(0, 0.01, n)] for i in range(k)}


def test_clean_dataset_is_good():
    out = DataQualityModel().run(_ds(_clean()), {}, 0)
    assert check_output(catalog.Q1_DATA_QUALITY, out) == []
    m = {k: v.value for k, v in out.metrics.items()}
    assert m == {"n_positions": 4, "history_days": 400, "missing_share": 0.0, "stale_series": 0, "outlier_count": 0}
    assert out.labels["quality"] == "good" and out.findings == []


def test_detects_injected_missing_stale_and_outliers():
    s = _clean()
    s["S0"][10] = None
    s["S0"][20] = None
    s["S1"][100:106] = [0.0] * 6
    s["S2"][50] = 0.25  # ~25 sigma
    s["S2"][51] = -0.30
    out = DataQualityModel().run(_ds(s), {"stale_days": 5}, 0)
    assert check_output(catalog.Q1_DATA_QUALITY, out) == []
    m = {k: v.value for k, v in out.metrics.items()}
    assert m["missing_share"] == pytest.approx(2 / 1200)
    assert m["stale_series"] == 1 and m["outlier_count"] == 2
    by = {(f.check, f.subject): f for f in out.findings}
    assert by[("missing_returns", "S0")].count == 2
    assert by[("stale_series", "S1")].count == 6
    assert by[("outlier_returns", "S2")].count == 2
    assert out.labels["quality"] == "fair"


def test_stale_threshold_parameter():
    s = _clean()
    s["S1"][100:104] = [0.0] * 4
    assert DataQualityModel().run(_ds(s), {"stale_days": 5}, 0).metrics["stale_series"].value == 0
    assert DataQualityModel().run(_ds(s), {"stale_days": 4}, 0).metrics["stale_series"].value == 1


def test_poor_when_missing_share_above_five_percent():
    s = _clean(k=2)
    for i in range(0, 400, 9):  # 45 of 800 values = 5.6%
        s["S0"][i] = None
    out = DataQualityModel().run(_ds(s), {}, 0)
    assert out.metrics["missing_share"].value > 0.05
    assert out.labels["quality"] == "poor"


def test_poor_when_series_shorter_than_250_days():
    out = DataQualityModel().run(_ds(_clean(n=200)), {}, 0)
    assert out.labels["quality"] == "poor"
    assert any(f.check == "short_history" and f.severity.value == "error" for f in out.findings)


def test_sample_dataset_findings():
    out = DataQualityModel().run(sample_dataset(), {}, 0)
    assert check_output(catalog.Q1_DATA_QUALITY, out) == []
    checks = {(f.check, f.subject) for f in out.findings}
    assert ("missing_returns", "HTLX") in checks and ("stale_series", "KILO") in checks
    assert out.metrics["stale_series"].value == 1
    assert out.metrics["history_days"].value == 780
    assert out.labels["quality"] == "fair"


def test_helpers():
    assert longest_zero_run(np.array([0, 0, 1, 0, 0, 0, np.nan, 0.0])) == 3
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.01, 200)
    x[100] = 0.25  # an isolated data error: flagged
    assert np.flatnonzero(outlier_mask(x)).tolist() == [100]
    regime = np.concatenate([rng.normal(0, 0.01, 150), rng.normal(0, 0.03, 150)])  # volatility tripling
    assert outlier_mask(regime).sum() <= 1  # a genuine regime change is not a data error
    assert not outlier_mask(np.zeros(100)).any()  # MAD = 0 -> no outliers
    assert not outlier_mask(np.array([0.0, 1, 50])).any()  # too few observations
