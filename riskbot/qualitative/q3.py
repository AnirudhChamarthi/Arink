"""Q3 rubric: how exposed is the portfolio to the low-carbon transition, and how reliable is the data?

Rules read ``q3.data_quality`` coverage metrics, ``q3.transition`` grid outputs, the comparison's
``loss_pct`` range and the climate-portfolio dataset (sectors, exclusion and controversy flags).
"""

from __future__ import annotations

from riskbot.contract.types import ClimatePortfolio
from riskbot.contract.types import ControlStrength as C

from ._base import FactorDef, Outcome
from ._inputs import (
    Inputs,
    MissingInput,
    band_down,
    band_up,
    comparison_evidence,
    plural,
    field_evidence,
    finding_evidence,
    label_evidence,
    safe_name,
    share_words,
)

TR, DQ = "q3.transition", "q3.data_quality"


def _portfolio(inp: Inputs) -> ClimatePortfolio:
    if not isinstance(inp.dataset, ClimatePortfolio):
        raise MissingInput("a climate-portfolio dataset")
    return inp.dataset


def _high_emitting_share(ds: ClimatePortfolio, sectors) -> tuple[float, list[int]]:
    long_mv = sum(h.market_value for h in ds.holdings if h.market_value > 0)
    idx = [i for i, h in enumerate(ds.holdings)
           if h.market_value > 0 and any(s in h.sector.lower() for s in sectors)]
    if long_mv <= 0:
        return 0.0, idx
    return sum(ds.holdings[i].market_value for i in idx) / long_mv, idx


def _quality_control(inp: Inputs, ev: list) -> C:
    res = inp.first(DQ)
    q = res.output.labels.get("quality") if res and res.output else None
    if q is None:
        return C.ADEQUATE
    ev.append(label_evidence(res, "quality"))
    return {"good": C.STRONG, "fair": C.ADEQUATE, "poor": C.WEAK}.get(q, C.ADEQUATE)


def emissions_coverage(inp: Inputs, fd: FactorDef) -> Outcome:
    cov = inp.require(DQ, "coverage_scope12")
    likelihood = band_down(cov.value, fd.params["coverage_cuts"])
    ev = cov.evidence("MV share with scope 1 and 2")
    control = _quality_control(inp, ev)
    rationale = (f"Reported scope 1 and 2 emissions cover {cov.text} of market value; the rest must be imputed, "
                 f"so measured exposure depends on proxies.")
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def estimated_emissions(inp: Inputs, fd: FactorDef) -> Outcome:
    refs = inp.grid_refs(TR, "estimated_share")
    if not refs:
        raise MissingInput(f"metric 'estimated_share' because {inp.why_missing(TR)}"
                           if not inp.grid(TR) else "metric 'estimated_share' in the transition outputs")
    est = max(refs, key=lambda r: r.value)
    likelihood = band_up(est.value, fd.params["share_cuts"])
    ev = est.evidence("Largest share of financed emissions imputed across the grid")
    mdq = inp.metric(DQ, "mean_data_quality")
    if mdq is None:
        control, q = C.ADEQUATE, ""
    else:
        control = (C.STRONG if mdq.value <= fd.params["dq_strong"] else
                   C.ADEQUATE if mdq.value <= fd.params["dq_adequate"] else C.WEAK)
        q = f", with a market-value-weighted data-quality score of {mdq.text} (one is best, five worst)"
        ev += mdq.evidence("MV-weighted data-quality score")
    rationale = f"Up to {est.text} of financed emissions are imputed rather than reported{q}."
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def scope3_coverage(inp: Inputs, fd: FactorDef) -> Outcome:
    cov = inp.require(DQ, "coverage_scope3")
    likelihood = band_down(cov.value, fd.params["coverage_cuts"])
    ev = cov.evidence("MV share with scope 3")
    impact, he_note = fd.default_impact, ""
    if isinstance(inp.dataset, ClimatePortfolio):
        share, idx = _high_emitting_share(inp.dataset, fd.params["high_emitting_sectors"])
        if share >= fd.params["material_high_emitting"]:
            impact = fd.params["impact_if_high_emitting"]
            he_note = ", and high-emitting sectors whose value chain emissions dominate are a material share"
            ev.append(field_evidence("holdings", "Sector and market value of each holding."))
    included = any(r.spec.params.get("include_scope3") is True for r in inp.grid(TR))
    scen = "" if included else "; the scenarios exclude scope 3"
    rationale = f"Scope 3 emissions are available for {cov.text} of market value{he_note}{scen}."
    return Outcome(likelihood, impact, C.ADEQUATE, rationale, ev)


def stale_data(inp: Inputs, fd: FactorDef) -> Outcome:
    st = inp.require(DQ, "stale_share")
    likelihood = band_up(st.value, fd.params["share_cuts"])
    ev = st.evidence("MV share with stale emissions")
    stale_findings = [f for f in inp.findings() if "stale" in f.check]
    ev += [finding_evidence(f) for f in stale_findings]
    rationale = (f"Emissions figures are stale for {st.text} of market value, so recent decarbonisation or "
                 f"growth is not reflected." if st.value > 0 else
                 f"Emissions figures are stale for {st.text} of market value; all data are within the staleness limit.")
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def controversies(inp: Inputs, fd: FactorDef) -> Outcome:
    cs = inp.require(DQ, "controversy_share")
    likelihood = band_up(cs.value, fd.params["share_cuts"])
    ev = cs.evidence("MV share with controversy flags")
    names = []
    if isinstance(inp.dataset, ClimatePortfolio):
        for i, h in enumerate(inp.dataset.holdings):
            if h.controversy_flags:
                ev.append(field_evidence(f"holdings[{i}].controversy_flags", f"{h.issuer}: {h.controversy_flags}."))
                names.append(safe_name(h.issuer, "an unnamed issuer"))
    who = f" ({', '.join(names[:3])}{' and others' if len(names) > 3 else ''})" if names else ""
    rationale = (f"Issuers with controversy flags{who} make up {cs.text} of market value, a reputational and "
                 f"greenwashing exposure." if cs.value > 0 else
                 f"Issuers with controversy flags make up {cs.text} of market value.")
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def exclusion_breaches(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _portfolio(inp)
    long_mv = sum(h.market_value for h in ds.holdings if h.market_value > 0)
    if long_mv <= 0:
        raise MissingInput("long holdings with positive market value")
    breaches = [(i, h) for i, h in enumerate(ds.holdings) if h.market_value > 0 and h.exclusion_flags]
    if not breaches:
        return Outcome(1, fd.default_impact, C.ADEQUATE,
                       "No long holding carries an exclusion flag, so the stated exclusion policy is respected.",
                       [field_evidence("holdings", "Exclusion flags of every holding are empty for long positions.")])
    share = sum(h.market_value for _, h in breaches) / long_mv
    impact = band_up(share, fd.params["mv_share_cuts"]) + 2
    names = [safe_name(h.issuer, "an unnamed issuer") for _, h in breaches]
    flags = sorted({f for _, h in breaches for f in h.exclusion_flags})
    rationale = (f"{plural(len(breaches), 'long holding').capitalize()} ({', '.join(names[:3])}"
                 f"{' and others' if len(names) > 3 else ''}) {'breaches' if len(breaches) == 1 else 'breach'} exclusions ({', '.join(flags[:4])}), "
                 f"{share_words(share)} of long market value; the stated policy is not enforced.")
    ev = [field_evidence(f"holdings[{i}].exclusion_flags", f"{h.issuer}: {h.exclusion_flags}.") for i, h in breaches]
    return Outcome(fd.params["likelihood_if_breach"], min(5, impact), C.WEAK, rationale, ev)


def high_emitting_concentration(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _portfolio(inp)
    if sum(h.market_value for h in ds.holdings if h.market_value > 0) <= 0:
        raise MissingInput("long holdings with positive market value")
    share, idx = _high_emitting_share(ds, fd.params["high_emitting_sectors"])
    likelihood = band_up(share, fd.params["share_cuts"])
    ev = [field_evidence(f"holdings[{i}].sector", f"{ds.holdings[i].issuer}: {ds.holdings[i].sector}.")
          for i in idx] or [field_evidence("holdings", "No holding is in a high-emitting sector.")]
    waci = inp.metric(TR, "waci")
    if waci is not None:
        ev += waci.evidence("Weighted average carbon intensity")
    sectors = sorted({ds.holdings[i].sector for i in idx})
    if idx:
        rationale = (f"Energy, utilities and materials holdings ({', '.join(safe_name(s, 'other') for s in sectors)}) "
                     f"are {share_words(share)} of long market value; their value is most sensitive to carbon "
                     f"prices.")
    else:
        rationale = "The portfolio holds nothing in energy, utilities or materials."
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def scenario_dispersion(inp: Inputs, fd: FactorDef) -> Outcome:
    refs = inp.grid_refs(TR, "loss_pct")
    if not refs:
        raise MissingInput(f"metric 'loss_pct' because {inp.why_missing(TR)}")
    lo = min(refs, key=lambda r: r.value)
    hi = max(refs, key=lambda r: r.value)
    ev = []
    if "loss_pct" in inp.comparison.metric_ranges:
        ev.append(comparison_evidence("metric_ranges.loss_pct", "Range of median loss across the grid."))
    ev += lo.evidence("Lowest loss across scenarios") + hi.evidence("Highest loss across scenarios")
    if hi.value <= 0:
        likelihood = 1
    elif lo.value <= 0:
        likelihood = 5
    else:
        likelihood = band_up(hi.value / lo.value, fd.params["ratio_cuts"])
    impact = band_up(max(0.0, hi.value), fd.params["max_loss_cuts"])

    def where(r):
        return ", ".join(f"{k} {r.params[k]}" for k in ("scenario", "price_path", "missing_data") if k in r.params)
    rationale = (f"The median transition loss ranges from {lo.text} ({where(lo)}) to {hi.text} ({where(hi)}), so "
                 f"the answer depends heavily on scenario and data assumptions." if likelihood >= 3 else
                 f"The median transition loss ranges from {lo.text} ({where(lo)}) to {hi.text} ({where(hi)}), "
                 f"a narrow range across scenarios and data assumptions.")
    return Outcome(likelihood, impact, C.ADEQUATE, rationale, ev)


_HIGH_EMITTING = ("energy", "utilit", "material")

RUBRIC: tuple[FactorDef, ...] = (
    FactorDef(
        "emissions_coverage", "Emissions coverage (scope 1-2)",
        "Market-value share with reported scope 1 and 2 emissions.", 3, emissions_coverage,
        inputs=("q3.data_quality: coverage_scope12, label quality",),
        control_basis="Data-quality label: good strong, fair adequate, poor weak.",
        params={"coverage_cuts": (0.90, 0.75, 0.60, 0.40)},
    ),
    FactorDef(
        "estimated_emissions", "Estimated (imputed) emissions",
        "Share of financed emissions that are imputed rather than reported.", 3, estimated_emissions,
        inputs=("q3.transition grid: estimated_share (maximum)", "q3.data_quality: mean_data_quality"),
        control_basis="MV-weighted PCAF-style score: strong <= 2, adequate <= 3.5, weak above.",
        params={"share_cuts": (0.10, 0.25, 0.40, 0.60), "dq_strong": 2.0, "dq_adequate": 3.5},
    ),
    FactorDef(
        "scope3_coverage", "Scope 3 coverage",
        "Market-value share with value-chain (scope 3) emissions.", 3, scope3_coverage,
        inputs=("q3.data_quality: coverage_scope3", "dataset.holdings[*].sector", "q3.transition params: include_scope3"),
        control_basis="No control evidence in the data: adequate by default.",
        params={"coverage_cuts": (0.75, 0.50, 0.30, 0.10), "high_emitting_sectors": _HIGH_EMITTING,
                "material_high_emitting": 0.20, "impact_if_high_emitting": 4},
    ),
    FactorDef(
        "stale_data", "Stale emissions data",
        "Market-value share whose emissions are older than the staleness threshold.", 2, stale_data,
        inputs=("q3.data_quality: stale_share", "findings with 'stale' in the check"),
        control_basis="No control evidence in the data: adequate by default.",
        params={"share_cuts": (1e-12, 0.10, 0.25, 0.50)},
    ),
    FactorDef(
        "controversies", "Controversies",
        "Market-value share of issuers with controversy flags.", 3, controversies,
        inputs=("q3.data_quality: controversy_share", "dataset.holdings[*].controversy_flags"),
        control_basis="No engagement data: adequate by default.",
        params={"share_cuts": (1e-12, 0.05, 0.15, 0.30)},
    ),
    FactorDef(
        "exclusion_breaches", "Exclusion-policy breaches",
        "Long holdings that carry an exclusion flag (a breach of the stated policy).", 3, exclusion_breaches,
        inputs=("dataset.holdings[*].exclusion_flags / market_value",),
        control_basis="Any breach shows the screen is not enforced (weak); otherwise adequate.",
        params={"likelihood_if_breach": 5, "mv_share_cuts": (0.02, 0.10)},
    ),
    FactorDef(
        "high_emitting_concentration", "High-emitting sector concentration",
        "Long market-value share in energy, utilities and materials.", 4, high_emitting_concentration,
        inputs=("dataset.holdings[*].sector / market_value", "q3.transition: waci"),
        control_basis="No transition-plan data: adequate by default.",
        params={"share_cuts": (0.10, 0.20, 0.30, 0.45), "high_emitting_sectors": _HIGH_EMITTING},
    ),
    FactorDef(
        "scenario_dispersion", "Scenario dispersion",
        "How much the transition loss varies across scenarios, price paths and data treatments.", 3,
        scenario_dispersion,
        inputs=("comparison.metric_ranges['loss_pct']", "q3.transition grid: loss_pct"),
        control_basis="Scenario analysis is itself the control (adequate).",
        params={"ratio_cuts": (1.5, 2.5, 4.0, 8.0), "max_loss_cuts": (0.02, 0.05, 0.10, 0.20)},
    ),
)
