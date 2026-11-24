r"""q3.data_quality: coverage and quality of emissions data, weighted by long market value.

For long holdings i (MV_i > 0) with weights w_i = MV_i / sum_j MV_j:

* coverage_scope12 = sum_i w_i 1[scope1_i and scope2_i reported]
* coverage_scope3  = sum_i w_i 1[scope3_i reported]
* mean_data_quality = sum_i w_i q_i, q_i = data_quality_i, or 5 when it is missing or scope 1/2 is missing
  (the holding would be imputed, i.e. a sector estimate in PCAF terms)
* stale_share = sum_i w_i 1[emissions_year_i < as_of.year - stale_years]
* controversy_share = sum_i w_i 1[controversy flags present]

quality: poor if coverage_scope12 < 60 %; fair if coverage_scope12 < 85 % or stale_share > 20 %; else good.
Findings are emitted for every holding (long or short) with an issue.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import DataQualityFinding, ModelOutput, ModelSpec, Severity, Unit

from ._common import as_portfolio, fmt
from .assumptions import normalise_sector


def quality_label(coverage_scope12: float, stale_share: float) -> str:
    """poor if coverage < 0.60; fair if coverage < 0.85 or stale_share > 0.20; else good."""
    if coverage_scope12 < 0.60:
        return "poor"
    if coverage_scope12 < 0.85 or stale_share > 0.20:
        return "fair"
    return "good"


def run_data_quality(dataset: Any, params: dict[str, Any] | None, seed: int) -> ModelOutput:
    spec = catalog.Q3_DATA_QUALITY
    p = as_portfolio(dataset, spec.model_id)
    prm = resolve_params(spec, params)
    cutoff = p.as_of.year - prm["stale_years"]
    findings: list[DataQualityFinding] = []

    def add(check: str, sev: Severity, field: str, subject: str, msg: str) -> None:
        findings.append(DataQualityFinding(check=check, severity=sev, field=field, subject=subject, count=1,
                                           message=msg))

    rows = []
    for h in p.holdings:
        has12 = h.scope1 is not None and h.scope2 is not None
        stale = h.emissions_year is not None and h.emissions_year < cutoff
        _, known = normalise_sector(h.sector)
        side = "" if h.market_value > 0 else " (short/zero holding)"
        if not has12:
            add("missing_scope12", Severity.WARNING, "scope1,scope2", h.issuer,
                f"Scope 1 and/or 2 emissions missing{side}; transition model must impute or exclude.")
        if h.scope3 is None:
            add("missing_scope3", Severity.INFO, "scope3", h.issuer, f"Scope 3 emissions missing{side}.")
        if stale:
            add("stale_emissions", Severity.WARNING, "emissions_year", h.issuer,
                f"Emissions year {h.emissions_year} is older than {cutoff} (as-of {p.as_of.year} - "
                f"{prm['stale_years']} years){side}.")
        if h.controversy_flags:
            add("controversy", Severity.WARNING, "controversy_flags", h.issuer,
                f"Controversy flags: {', '.join(h.controversy_flags)}{side}.")
        if h.exclusion_flags:
            add("exclusion_breach", Severity.WARNING, "exclusion_flags", h.issuer,
                f"Exclusion-policy flags: {', '.join(h.exclusion_flags)}{side}.")
        if not known:
            add("unknown_sector", Severity.WARNING, "sector", h.issuer,
                f"Sector {h.sector!r} not recognised; treated as 'other'{side}.")
        q = 5 if (h.data_quality is None or not has12) else h.data_quality
        if h.market_value > 0:
            rows.append({"issuer": h.issuer, "market_value": h.market_value, "scope12": has12,
                         "scope3": h.scope3 is not None, "data_quality_used": q,
                         "emissions_year": h.emissions_year, "stale": stale,
                         "controversy": bool(h.controversy_flags), "exclusion": bool(h.exclusion_flags)})

    mv = np.array([r["market_value"] for r in rows], dtype=float)
    total = float(mv.sum())
    if total > 0:
        w = mv / total
    else:
        w = mv
        add("no_long_holdings", Severity.ERROR, "market_value", p.name, "No long holdings: shares set to 0.")

    def share(key: str) -> float:
        return float(sum(wi for wi, r in zip(w, rows) if r[key]))

    cov12, cov3 = share("scope12"), share("scope3")
    stale_share, contro = share("stale"), share("controversy")
    mean_q = float(sum(wi * r["data_quality_used"] for wi, r in zip(w, rows))) if total > 0 else 5.0
    label = quality_label(cov12, stale_share)

    tb = TraceBuilder(spec.model_id, "Climate data quality", model_input_hash(spec.model_id, p, prm, seed),
                      assumptions=["Weights are long market value shares; shorts only appear in findings.",
                                   "Missing data_quality, or missing scope 1/2, scores 5 (sector estimate).",
                                   "Thresholds for the quality label are illustrative."],
                      inputs={**prm, "seed": seed, "n_holdings": len(p.holdings), "n_long": len(rows)})
    tb.step("holdings", "Per-holding data flags (long book)", r"w_i = MV_i / \sum_j MV_j",
            f"{len(rows)} long holdings, MV {fmt(total, 2)}", value=total, unit=Unit.CURRENCY, table=rows or None)
    for key, title, formula, val, unit in (
        ("coverage_scope12", "Scope 1+2 coverage", r"\sum_i w_i 1[S1_i, S2_i]", cov12, Unit.FRACTION),
        ("coverage_scope3", "Scope 3 coverage", r"\sum_i w_i 1[S3_i]", cov3, Unit.FRACTION),
        ("mean_data_quality", "Mean data-quality score", r"\sum_i w_i q_i", mean_q, Unit.RATIO),
        ("stale_share", "Stale emissions share", rf"\sum_i w_i 1[year_i < {cutoff}]", stale_share, Unit.FRACTION),
        ("controversy_share", "Controversy share", r"\sum_i w_i 1[flags_i \neq \emptyset]", contro, Unit.FRACTION),
    ):
        tb.step(key, title, formula, f"{val:.6f}", value=val, unit=unit)
    tb.step("quality", "Quality label",
            r"poor: cov_{12} < 0.6;\ fair: cov_{12} < 0.85 \lor stale > 0.2;\ good",
            f"coverage_scope12 = {cov12:.4f}, stale_share = {stale_share:.4f} -> {label}", value=None)
    vals = {"coverage_scope12": (cov12, Unit.FRACTION), "coverage_scope3": (cov3, Unit.FRACTION),
            "mean_data_quality": (mean_q, Unit.RATIO), "stale_share": (stale_share, Unit.FRACTION),
            "controversy_share": (contro, Unit.FRACTION)}
    metrics = {k: tb.metric(k, v, u) for k, (v, u) in vals.items()}
    trace = tb.build(result={k: v for k, (v, _) in vals.items()})
    return ModelOutput(model_id=spec.model_id, params=prm, metrics=metrics, labels={"quality": label},
                       traces=[trace], findings=findings, warnings=tb.warnings)


class DataQualityModel:
    """Model protocol implementation for catalog.Q3_DATA_QUALITY."""

    spec: ModelSpec = catalog.Q3_DATA_QUALITY

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        return run_data_quality(dataset, params, seed)
