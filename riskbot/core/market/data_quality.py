"""``q1.data_quality``: missing values, stale series, outliers and history length of a market dataset.

Checks (per return series of a held, non-cash ticker)
-----------------------------------------------------
* missing: count of ``None`` values; ``missing_share`` = missing / all values over held series.
* stale: a run of at least ``stale_days`` consecutive returns exactly equal to 0 (a frozen price).
* outliers: :math:`|r_t-\\mathrm{med}(r)|>8\\,\\mathrm{MAD}`, :math:`\\mathrm{MAD}=\\mathrm{med}|r_t-\\mathrm{med}(r)|`
  (raw MAD, no 1.4826 consistency factor; missing values ignored).
* short history: fewer than 250 non-missing values.

Label ``quality``: ``poor`` if missing_share > 5% or any series has < 250 values; ``fair`` if any finding has
severity warning; otherwise ``good``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import DataQualityFinding, ModelOutput, Severity, TableCell, Unit

from ._data import as_market_dataset

OUTLIER_MADS = 8.0
MIN_SERIES_DAYS = 250
POOR_MISSING_SHARE = 0.05


def longest_zero_run(x: np.ndarray) -> int:
    """Length of the longest run of consecutive values exactly equal to 0 (NaN breaks a run)."""
    best = cur = 0
    for v in x:
        if v == 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def outlier_mask(x: np.ndarray, k: float = OUTLIER_MADS) -> np.ndarray:
    """Boolean mask of :math:`|x-\\mathrm{med}|>k\\,\\mathrm{MAD}` over finite values (False where MAD = 0)."""
    finite = np.isfinite(x)
    mask = np.zeros(x.shape, dtype=bool)
    if finite.sum() < 3:
        return mask
    v = x[finite]
    med = np.median(v)
    mad = np.median(np.abs(v - med))
    if mad <= 0:
        return mask
    mask[finite] = np.abs(v - med) > k * mad
    return mask


class DataQualityModel:
    """Implements ``catalog.Q1_DATA_QUALITY``."""

    spec = catalog.Q1_DATA_QUALITY

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        mid = self.spec.model_id
        eff = resolve_params(self.spec, params)
        ds = as_market_dataset(dataset, mid)
        stale_days = eff["stale_days"]
        tb = TraceBuilder(mid, "Market data quality", model_input_hash(mid, ds, eff, seed),
                          assumptions=["Only return series of held non-cash positions are checked.",
                                       "A run of exactly-zero returns indicates a stale (frozen) price.",
                                       "Outliers: |r - median| > 8 x raw MAD per series."],
                          inputs={"params": eff, "seed": seed, "dataset": ds.name, "synthetic": ds.synthetic})
        findings: list[DataQualityFinding] = []
        held = []
        for p in ds.positions:
            if p.asset_class != "cash" and p.ticker not in held:
                held.append(p.ticker)
        n = len(ds.dates)
        rows: list[dict[str, TableCell]] = []
        total_missing = stale_series = outliers = 0
        short = 0
        for t in held:
            x = np.array([np.nan if v is None else float(v) for v in ds.returns[t]], dtype=float)
            miss = int(np.isnan(x).sum())
            run = longest_zero_run(x)
            is_stale = run >= stale_days
            om = outlier_mask(x)
            n_out = int(om.sum())
            valid = n - miss
            total_missing += miss
            stale_series += int(is_stale)
            outliers += n_out
            if miss:
                findings.append(DataQualityFinding(check="missing_returns", severity=Severity.WARNING, field="returns",
                                                   subject=t, count=miss,
                                                   message=f"{t}: {miss} missing return(s) of {n}."))
            if is_stale:
                findings.append(DataQualityFinding(check="stale_series", severity=Severity.WARNING, field="returns",
                                                   subject=t, count=run,
                                                   message=f"{t}: run of {run} consecutive zero returns "
                                                           f"(threshold {stale_days})."))
            if n_out:
                dates = [ds.dates[i].isoformat() for i in np.flatnonzero(om)][:5]
                findings.append(DataQualityFinding(check="outlier_returns", severity=Severity.WARNING, field="returns",
                                                   subject=t, count=n_out,
                                                   message=f"{t}: {n_out} return(s) beyond 8 MAD from the median "
                                                           f"(first: {', '.join(dates)})."))
            if valid < MIN_SERIES_DAYS:
                short += 1
                findings.append(DataQualityFinding(check="short_history", severity=Severity.ERROR, field="returns",
                                                   subject=t, count=valid,
                                                   message=f"{t}: only {valid} non-missing returns "
                                                           f"(< {MIN_SERIES_DAYS})."))
            rows.append({"ticker": t, "missing": miss, "longest_zero_run": run, "stale": is_stale,
                         "outliers": n_out, "valid_days": valid})
        total = n * len(held)
        share = total_missing / total if total else 0.0

        tb.step("n_positions", "Positions", r"\#\mathrm{positions}", f"{len(ds.positions)} positions, "
                f"{len(held)} with return series", value=len(ds.positions), unit=Unit.COUNT)
        tb.step("history_days", "Length of the return history", r"\#\mathrm{dates}",
                f"{n} dates" + (f" from {ds.dates[0].isoformat()} to {ds.dates[-1].isoformat()}" if n else ""),
                value=n, unit=Unit.DAYS)
        tb.step("missing_share", "Share of missing return values", r"\frac{\#\mathrm{missing}}{n\cdot k}",
                f"{total_missing} / ({n} x {len(held)}) = {share:.6g}", value=share, unit=Unit.FRACTION, table=rows)
        tb.step("stale_series", "Series with a stale run", r"\#\{i:\ \mathrm{maxrun}_i(r=0)\ge d\}",
                f"d = {stale_days}: {stale_series} series", value=stale_series, unit=Unit.COUNT)
        tb.step("outlier_count", "Outlier returns", r"\sum_i\#\{t:|r_{ti}-\mathrm{med}_i|>8\,\mathrm{MAD}_i\}",
                f"{outliers} outliers", value=outliers, unit=Unit.COUNT)
        if share > POOR_MISSING_SHARE or short:
            quality = "poor"
        elif any(f.severity == Severity.WARNING for f in findings):
            quality = "fair"
        else:
            quality = "good"
        tb.step("quality", "Quality label",
                r"\mathrm{poor}\iff s_{miss}>5\%\ \vee\ \exists i: n_i<250;\ \mathrm{fair}\iff\exists\ \mathrm{warning}",
                f"missing_share = {share:.4g}, short series = {short}, warnings = "
                f"{sum(f.severity == Severity.WARNING for f in findings)} -> {quality}")
        metrics = {
            "n_positions": tb.metric("n_positions", len(ds.positions), Unit.COUNT),
            "history_days": tb.metric("history_days", n, Unit.DAYS),
            "missing_share": tb.metric("missing_share", share, Unit.FRACTION),
            "stale_series": tb.metric("stale_series", stale_series, Unit.COUNT),
            "outlier_count": tb.metric("outlier_count", outliers, Unit.COUNT),
        }
        trace = tb.build(result={k: m.value for k, m in metrics.items()})
        return ModelOutput(model_id=mid, params=eff, metrics=metrics, labels={"quality": quality}, traces=[trace],
                           findings=findings, warnings=[])
