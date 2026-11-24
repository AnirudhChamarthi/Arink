r"""q3.transition: carbon-price valuation shock, WACI, financed emissions and alignment.

Mathematics (full derivation in README.md)
-----------------------------------------
For each long holding i (market value MV_i > 0) with emissions E_i (tCO2e/yr), EVIC_i and sector s(i):

* carbon price in year t after the as-of year:  p_t = m * P_scenario(t)   (USD/tCO2e, illustrative)
* annual unpassed carbon cost:  C_{i,t} = E_i * p_t * (1 - pi_s)           (emissions held constant)
* present value over the horizon H at rate r:  PV_i = E_i (1 - pi_s) A,  A = sum_{t=1}^{H} p_t (1+r)^{-t}
* value shock:  shock_i = -min(PV_i / EVIC_i, 1)   (capped at -100 %)
* holding loss: L_i = MV_i * min(PV_i / EVIC_i, 1)

Uncertainty: E_i^{(k)} = E_i exp(sigma_i Z_{ik} - sigma_i^2 / 2), Z ~ N(0,1) i.i.d., k = 1..n_sims, so that
E[E_i^{(k)}] = E_i. Portfolio loss per draw L^{(k)} = sum_i MV_i min(c_i exp(sigma_i Z_ik - sigma_i^2/2), 1)
with c_i = PV_i / EVIC_i; loss_pct = median_k L^{(k)} / MV_long, loss_p05 / loss_p95 empirical quantiles.

Footprint metrics (PCAF / TCFD):
* WACI = sum_i w_i E_i / Rev_i  (Rev in USD million), w_i = MV_i / sum of covered long MV
* financed emissions FE = sum_i (MV_i / EVIC_i) E_i
* estimated_share = FE of imputed holdings / FE
* alignment_ratio = WACI / (sum_s w_s B_s (1 - d)^{(year - 2020)})
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import (
    ClimatePortfolio,
    DataQualityFinding,
    Metric,
    ModelOutput,
    ModelSpec,
    Severity,
    Unit,
)

from ._common import MUSD, as_portfolio, fmt
from .assumptions import DEFAULT_ASSUMPTIONS, TransitionAssumptions, normalise_sector

# ---------------------------------------------------------------------------------------------
# Pure building blocks (individually tested)
# ---------------------------------------------------------------------------------------------


def price_schedule(scenario: str, price_path: str, horizon_years: int,
                   a: TransitionAssumptions = DEFAULT_ASSUMPTIONS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Years t = 0..H, scaled prices p_t = m P(t) and discount factors (1 + r)^{-t}."""
    t = np.arange(horizon_years + 1)
    prices = np.array([a.price(scenario, int(k), price_path) for k in t], dtype=float)
    disc = (1.0 + a.discount_rate) ** (-t.astype(float))
    return t, prices, disc


def discounted_price_sum(prices: np.ndarray, disc: np.ndarray) -> float:
    r"""A = \sum_{t=1}^{H} p_t (1+r)^{-t}: PV of paying one tonne's carbon price each year (end-of-year)."""
    return float(np.sum(prices[1:] * disc[1:]))


def loss_ratio(emissions: np.ndarray, pass_through: np.ndarray, annuity: float, evic: np.ndarray) -> np.ndarray:
    """Uncapped c_i = PV_i / EVIC_i = E_i (1 - pi_i) A / EVIC_i."""
    return emissions * (1.0 - pass_through) * annuity / evic


def simulate_portfolio_losses(c: np.ndarray, mv: np.ndarray, sigma: np.ndarray, z: np.ndarray) -> np.ndarray:
    r"""Portfolio loss per draw: L^{(k)} = \sum_i MV_i \min(c_i e^{\sigma_i Z_{ki} - \sigma_i^2/2}, 1).

    ``z`` has shape (n_sims, n_holdings). With sigma = 0 every draw equals the deterministic loss.
    """
    factor = np.exp(sigma[None, :] * z - 0.5 * sigma[None, :] ** 2)
    return np.minimum(c[None, :] * factor, 1.0) @ mv


def sector_intensity_stats(intensities: dict[str, list[float]], q: float) -> dict[str, float]:
    """Per-sector q-quantile (0.5 median, 0.75 conservative) of reported intensities (linear interpolation)."""
    return {s: float(np.quantile(v, q)) for s, v in intensities.items() if v}


# ---------------------------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------------------------


@dataclass
class _Row:
    issuer: str
    sector: str
    mv: float
    evic: float
    rev_musd: float
    emissions: float | None  # None when excluded
    source: str  # reported / imputed / excluded
    sigma: float
    pass_through: float
    intensity_used: str = ""


def _emissions_rows(p: ClimatePortfolio, params: dict[str, Any], a: TransitionAssumptions,
                    findings: list[DataQualityFinding]) -> tuple[list[_Row], list[dict], dict[str, Any]]:
    """Classify holdings, impute missing scope 1+2 and return the long rows plus a short-book table."""
    method = params["missing_data"]
    q = 0.75 if method == "conservative" else 0.5
    norm: list[tuple[Any, str]] = []
    for h in p.holdings:
        sec, known = normalise_sector(h.sector)
        if not known:
            findings.append(DataQualityFinding(
                check="unknown_sector", severity=Severity.WARNING, field="sector", subject=h.issuer, count=1,
                message=f"Sector {h.sector!r} is not in the reference table; treated as 'other'."))
        norm.append((h, sec))

    # Peer intensities (scope 1+2 per USD m revenue) from every holding that reports both scopes.
    peers: dict[str, list[float]] = {}
    for h, sec in norm:
        if h.scope1 is not None and h.scope2 is not None:
            peers.setdefault(sec, []).append((h.scope1 + h.scope2) / (h.revenue / MUSD))
    peer_q = sector_intensity_stats(peers, q)

    rows: list[_Row] = []
    shorts: list[dict] = []
    for h, sec in norm:
        if h.market_value <= 0:
            shorts.append({"issuer": h.issuer, "sector": sec, "market_value": h.market_value,
                           "treatment": "short or zero: excluded from exposure"})
            continue
        pt = a.pass_through[sec]
        rev_musd = h.revenue / MUSD
        s3 = h.scope3 if (params["include_scope3"] and h.scope3 is not None) else 0.0
        if h.scope1 is not None and h.scope2 is not None:
            rows.append(_Row(h.issuer, sec, h.market_value, h.evic, rev_musd, h.scope1 + h.scope2 + s3,
                             "reported", a.sigma(h.data_quality, False), pt, "reported"))
            continue
        partial = "partial (one scope reported, ignored)" if (h.scope1 is not None or h.scope2 is not None) else ""
        if method == "exclude":
            rows.append(_Row(h.issuer, sec, h.market_value, h.evic, rev_musd, None, "excluded", 0.0, pt,
                             "excluded" + (f"; {partial}" if partial else "")))
            continue
        if sec in peer_q:
            inten, basis = peer_q[sec], f"peer {'p75' if q == 0.75 else 'median'} of {len(peers[sec])}"
        else:
            ref = a.sector_reference[sec]
            inten = ref.p75 if q == 0.75 else ref.median
            basis = f"fallback table {'p75' if q == 0.75 else 'median'}"
        rows.append(_Row(h.issuer, sec, h.market_value, h.evic, rev_musd, rev_musd * inten + s3, "imputed",
                         a.sigma_imputed, pt, f"{basis}: {inten:.1f} t/USDm" + (f"; {partial}" if partial else "")))
    return rows, shorts, peer_q


def run_transition(dataset: Any, params: dict[str, Any] | None, seed: int,
                   assumptions: TransitionAssumptions = DEFAULT_ASSUMPTIONS) -> ModelOutput:
    """Compute q3.transition. ``assumptions`` exists so tests can swap in alternative (illustrative) tables."""
    spec = catalog.Q3_TRANSITION
    portfolio = as_portfolio(dataset, spec.model_id)
    prm = resolve_params(spec, params)
    a = assumptions
    findings: list[DataQualityFinding] = []
    rows, shorts, _ = _emissions_rows(portfolio, prm, a, findings)
    if not rows:
        raise ValidationFailed("q3.transition needs at least one long holding (market_value > 0)",
                               model_id=spec.model_id)
    year0 = portfolio.as_of.year
    H = prm["horizon_years"]
    scen, path = prm["scenario"], prm["price_path"]

    input_hash = model_input_hash(spec.model_id, portfolio, prm, seed)
    assumptions_text = [
        "ILLUSTRATIVE scenario: carbon-price paths are NGFS-style shapes, not NGFS data.",
        "ILLUSTRATIVE sector pass-through rates, fallback intensities and benchmark pathway.",
        "Emissions held constant at the latest value over the horizon (no abatement, no growth).",
        f"Carbon cost paid at the end of each year t = 1..{H}, discounted at {a.discount_rate:.0%} per year.",
        "Value shock = -PV(unpassed carbon cost) / EVIC, capped at -100%; applied to long market value only.",
        "Monetary fields (market value, EVIC, revenue) are in currency units; carbon prices in the same "
        "currency (USD assumed); intensities per USD million of revenue.",
        "A holding counts as reported only if both scope 1 and scope 2 are present.",
        "Emission uncertainty: independent mean-preserving log-normal factors per holding (no correlation).",
    ]
    if portfolio.currency.upper() != "USD":
        assumptions_text.append(f"Dataset currency {portfolio.currency} treated as USD for carbon prices.")
    tb = TraceBuilder(spec.model_id, "Transition-risk valuation shock", input_hash, assumptions=assumptions_text,
                      inputs={**prm, "seed": seed, "as_of": portfolio.as_of.isoformat(),
                              "n_holdings": len(portfolio.holdings), "n_long": len(rows), "n_short": len(shorts)})

    # 1. Long book -------------------------------------------------------------------------
    mv = np.array([r.mv for r in rows])
    long_mv = float(mv.sum())
    excluded = [r for r in rows if r.source == "excluded"]
    excluded_mv = float(sum(r.mv for r in excluded))
    tb.step("long_book", "Long market value (shorts excluded)", r"MV_{long} = \sum_{i: MV_i > 0} MV_i",
            f"{len(rows)} long holdings, MV_long = {fmt(long_mv, 2)}; {len(shorts)} short/zero excluded; "
            f"excluded for missing data: {len(excluded)} holdings, MV {fmt(excluded_mv, 2)}",
            value=long_mv, unit=Unit.CURRENCY, table=shorts or None,
            note="Table lists short or zero holdings, reported and excluded from every exposure metric.")
    for s in shorts:
        findings.append(DataQualityFinding(
            check="short_excluded", severity=Severity.INFO, field="market_value", subject=s["issuer"], count=1,
            message=f"Short holding (MV {s['market_value']:.0f}) excluded from transition exposure."))
    for r in rows:
        if r.source == "imputed":
            findings.append(DataQualityFinding(
                check="imputed_emissions", severity=Severity.WARNING, field="scope1,scope2", subject=r.issuer,
                count=1, message=f"Scope 1+2 imputed ({prm['missing_data']}): {r.intensity_used}."))
        elif r.source == "excluded":
            findings.append(DataQualityFinding(
                check="excluded_missing_emissions", severity=Severity.WARNING, field="scope1,scope2",
                subject=r.issuer, count=1,
                message=f"Scope 1+2 missing; holding (MV {r.mv:.0f}) not shocked and not in emissions metrics."))

    # 2. Price path -----------------------------------------------------------------------
    t, prices, disc = price_schedule(scen, path, H, a)
    annuity = discounted_price_sum(prices, disc)
    price_end = float(prices[-1])
    m = a.price_multipliers[path]
    tb.step("carbon_price_end", f"Carbon-price path ({scen}, {path} = {m}x; illustrative)",
            r"p_t = m\,P_{scenario}(t),\quad A = \sum_{t=1}^{H} p_t (1+r)^{-t}",
            f"p_H = p_{{{year0 + H}}} = {fmt(price_end, 2)} USD/t; A = {fmt(annuity, 4)} USD per t/yr "
            f"(r = {a.discount_rate}, H = {H})",
            value=price_end, unit=Unit.CURRENCY,
            table=[{"year": int(year0 + k), "t": int(k), "price": float(prices[k]), "discount_factor": float(disc[k])}
                   for k in t])

    # 3. Per-holding shock -----------------------------------------------------------------
    cov = [i for i, r in enumerate(rows) if r.emissions is not None]
    E = np.array([r.emissions if r.emissions is not None else 0.0 for r in rows])
    pt = np.array([r.pass_through for r in rows])
    evic = np.array([r.evic for r in rows])
    sig = np.array([r.sigma for r in rows])
    c = loss_ratio(E, pt, annuity, evic)
    pv = c * evic
    capped = np.minimum(c, 1.0)
    central_losses = mv * capped
    central_loss = float(central_losses.sum())
    central_pct = central_loss / long_mv
    table = []
    for i, r in enumerate(rows):
        table.append({
            "issuer": r.issuer, "sector": r.sector, "market_value": r.mv, "evic": r.evic,
            "emissions_tco2e": r.emissions, "source": r.source, "basis": r.intensity_used,
            "sigma": r.sigma, "pass_through": r.pass_through, "pv_cost": float(pv[i]),
            "shock": float(-capped[i]), "capped": bool(c[i] > 1.0), "central_loss": float(central_losses[i]),
        })
    n_capped = int((c > 1.0).sum())
    if n_capped:
        tb.warn(f"{n_capped} holding(s) hit the -100% shock cap.")
    tb.step("central_loss", "Deterministic central loss (sigma = 0)",
            r"\frac{1}{MV_{long}}\sum_i MV_i \min\left(\frac{E_i (1-\pi_{s(i)}) A}{EVIC_i}, 1\right)",
            f"{fmt(central_loss, 2)} / {fmt(long_mv, 2)} = {central_pct:.6f}",
            value=central_pct, unit=Unit.FRACTION, table=table,
            note="Per-holding table: emissions source, sigma, pass-through, PV of carbon cost, shock and loss.")

    # 4. Footprint: WACI, financed emissions, estimated share ---------------------------------
    cov_mv = float(mv[cov].sum()) if cov else 0.0
    if cov_mv > 0:
        w = np.zeros(len(rows))
        w[cov] = mv[cov] / cov_mv
        rev = np.array([r.rev_musd for r in rows])
        intensity = E / rev
        waci = float(np.sum(w * intensity))
    else:
        w = np.zeros(len(rows))
        intensity = np.zeros(len(rows))
        waci = 0.0
        tb.warn("No long holding has emissions; WACI and alignment set to 0.")
    tb.step("waci", "Weighted average carbon intensity (TCFD)",
            r"WACI = \sum_i w_i \frac{E_i}{Rev_i},\quad w_i = \frac{MV_i}{\sum_{j \in covered} MV_j}",
            " + ".join(f"{w[i]:.4f}x{intensity[i]:.2f}" for i in cov) + f" = {waci:.4f} tCO2e/USDm",
            value=waci, unit=Unit.TCO2E_PER_MUSD,
            table=[{"issuer": rows[i].issuer, "weight": float(w[i]), "intensity": float(intensity[i])} for i in cov])
    attr = mv / evic
    fe_i = attr * E
    fe = float(fe_i.sum())
    tb.step("financed_emissions", "Financed emissions (PCAF attribution MV / EVIC)",
            r"FE = \sum_i \frac{MV_i}{EVIC_i} E_i",
            " + ".join(f"{attr[i]:.3e}x{fmt(E[i], 1)}" for i in cov) + f" = {fe:.4f} tCO2e",
            value=fe, unit=Unit.TCO2E,
            table=[{"issuer": rows[i].issuer, "attribution": float(attr[i]), "financed_tco2e": float(fe_i[i]),
                    "source": rows[i].source} for i in cov])
    imputed_idx = [i for i, r in enumerate(rows) if r.source == "imputed"]
    fe_imp = float(fe_i[imputed_idx].sum()) if imputed_idx else 0.0
    est_share = fe_imp / fe if fe > 0 else 0.0
    tb.step("estimated_share", "Share of financed emissions that is imputed",
            r"\frac{\sum_{i \in imputed} FE_i}{FE}", f"{fe_imp:.4f} / {fe:.4f} = {est_share:.6f}",
            value=est_share, unit=Unit.FRACTION)

    # 5. Alignment --------------------------------------------------------------------------
    sector_w: dict[str, float] = {}
    for i in cov:
        sector_w[rows[i].sector] = sector_w.get(rows[i].sector, 0.0) + float(w[i])
    bench = sum(wt * a.sector_reference[s].benchmark_2020 for s, wt in sector_w.items())
    factor = a.pathway_factor(year0)
    pathway = bench * factor
    tb.step("pathway_intensity", "Budget-pathway intensity (illustrative benchmark)",
            r"I^{path} = \Big(\sum_s w_s B_s\Big)(1-d)^{(year - 2020)}",
            f"{bench:.4f} x (1 - {a.pathway_decline})^{year0 - a.pathway_base_year} = {pathway:.4f}",
            value=pathway, unit=Unit.TCO2E_PER_MUSD,
            table=[{"sector": s, "weight": wt, "benchmark_2020": a.sector_reference[s].benchmark_2020}
                   for s, wt in sorted(sector_w.items())])
    alignment = waci / pathway if pathway > 0 else 0.0
    tb.step("alignment_ratio", "Alignment ratio", r"\frac{WACI}{I^{path}}",
            f"{waci:.4f} / {pathway:.4f} = {alignment:.6f}", value=alignment, unit=Unit.RATIO,
            note="> 1 means the portfolio is more carbon-intensive than its sector-weighted pathway.")

    # 6. Monte Carlo ------------------------------------------------------------------------
    n = prm["n_sims"]
    z = np.random.default_rng(seed).standard_normal((n, len(rows)))
    sims = simulate_portfolio_losses(c, mv, sig, z) / long_mv
    q05, q50, q95 = (float(x) for x in np.quantile(sims, [0.05, 0.5, 0.95]))
    loss_amount = q50 * long_mv
    level = "low" if q50 < a.low_threshold else "moderate" if q50 < a.moderate_threshold else "high"
    tb.step("loss_pct", "Monte Carlo median loss / long MV",
            r"\operatorname{median}_k \frac{1}{MV_{long}} \sum_i MV_i \min\left(c_i e^{\sigma_i Z_{ki} - \sigma_i^2/2}, 1\right)",
            f"median of {n} draws = {q50:.6f} (central sigma=0: {central_pct:.6f}); exposure_level = {level} "
            f"(low < {a.low_threshold:.0%} <= moderate < {a.moderate_threshold:.0%} <= high)",
            value=q50, unit=Unit.FRACTION,
            table=[{"statistic": k, "value": v} for k, v in (
                ("p05", q05), ("median", q50), ("p95", q95), ("mean", float(sims.mean())),
                ("std", float(sims.std(ddof=1)) if n > 1 else 0.0), ("central", central_pct))])
    tb.step("loss_p05", "Monte Carlo 5th percentile of loss", r"Q_{0.05}(L/MV_{long})", f"{q05:.6f}",
            value=q05, unit=Unit.FRACTION)
    tb.step("loss_p95", "Monte Carlo 95th percentile of loss", r"Q_{0.95}(L/MV_{long})", f"{q95:.6f}",
            value=q95, unit=Unit.FRACTION)
    tb.step("loss_amount", "Median loss in currency", r"loss\_pct \times MV_{long}",
            f"{q50:.6f} x {fmt(long_mv, 2)} = {fmt(loss_amount, 2)}", value=loss_amount, unit=Unit.CURRENCY)

    links = {
        "loss_pct": ("loss_pct", q50, Unit.FRACTION),
        "loss_p05": ("loss_p05", q05, Unit.FRACTION),
        "loss_p95": ("loss_p95", q95, Unit.FRACTION),
        "loss_amount": ("loss_amount", loss_amount, Unit.CURRENCY),
        "waci": ("waci", waci, Unit.TCO2E_PER_MUSD),
        "financed_emissions": ("financed_emissions", fe, Unit.TCO2E),
        "carbon_price_end": ("carbon_price_end", price_end, Unit.CURRENCY),
        "alignment_ratio": ("alignment_ratio", alignment, Unit.RATIO),
        "estimated_share": ("estimated_share", est_share, Unit.FRACTION),
    }
    metrics: dict[str, Metric] = {k: tb.metric(step, v, u) for k, (step, v, u) in links.items()}
    trace = tb.build(result={k: v for k, (_, v, _) in links.items()})
    return ModelOutput(model_id=spec.model_id, params=prm, metrics=metrics, labels={"exposure_level": level},
                       traces=[trace], findings=findings, warnings=tb.warnings)


class TransitionModel:
    """Model protocol implementation for catalog.Q3_TRANSITION."""

    spec: ModelSpec = catalog.Q3_TRANSITION

    def __init__(self, assumptions: TransitionAssumptions = DEFAULT_ASSUMPTIONS) -> None:
        self.assumptions = assumptions

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        return run_transition(dataset, params, seed, self.assumptions)
