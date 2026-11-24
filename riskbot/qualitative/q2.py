"""Q2 rubric: could a bank-like balance sheet survive a rate shock plus a deposit run?

Rules read the ``q2.data_quality`` structural indicators, ``q2.resilience`` grid outputs, the
``q2.reverse_stress`` break-evens, the comparison's conclusion flips, and the balance-sheet dataset.
"""

from __future__ import annotations

from riskbot.contract.types import BankBalanceSheet
from riskbot.contract.types import ControlStrength as C

from ._base import FactorDef, Outcome
from ._inputs import (
    Inputs,
    MissingInput,
    band_down,
    band_up,
    comparison_evidence,
    count_words,
    field_evidence,
    label_evidence,
    safe_name,
    share_words,
)

RES, REV, DQ = "q2.resilience", "q2.reverse_stress", "q2.data_quality"


def _bank(inp: Inputs) -> BankBalanceSheet:
    if not isinstance(inp.dataset, BankBalanceSheet):
        raise MissingInput("a balance-sheet dataset")
    return inp.dataset


def uninsured_deposits(inp: Inputs, fd: FactorDef) -> Outcome:
    u = inp.require(DQ, "uninsured_deposit_share")
    likelihood = band_up(u.value, fd.params["share_cuts"])
    ev = u.evidence("Uninsured deposits / all deposits")
    fast_liquidity_fail = [r for r in inp.grid(RES) if r.spec.params.get("run_speed") == "fast" and r.output
                           and r.output.labels.get("verdict") == "fail"
                           and r.output.labels.get("binding_constraint") in ("liquidity", "both")]
    impact = fd.default_impact
    run_note = ""
    if fast_liquidity_fail:
        impact = fd.params["impact_if_fast_run_fails"]
        run_note = "; a fast run breaches the liquidity constraint in at least one scenario"
        ev += [label_evidence(fast_liquidity_fail[0], "verdict"), label_evidence(fast_liquidity_fail[0],
                                                                                "binding_constraint")]
    hqla = inp.metric(DQ, "hqla_share")
    if hqla is None:
        control, buf = C.ADEQUATE, ""
    else:
        control = (C.STRONG if hqla.value >= fd.params["hqla_strong"] else
                   C.ADEQUATE if hqla.value >= fd.params["hqla_adequate"] else C.WEAK)
        buf = f", against an HQLA buffer of {hqla.text} of assets"
        ev += hqla.evidence("HQLA / total assets")
    rationale = (f"Uninsured deposits are {u.text} of all deposits{buf}{run_note}; uninsured depositors run "
                 f"first and fastest.")
    return Outcome(likelihood, impact, control, rationale, ev)


def deposit_concentration(inp: Inputs, fd: FactorDef) -> Outcome:
    s = inp.require(DQ, "largest_segment_share")
    likelihood = band_up(s.value, fd.params["share_cuts"])
    ev = s.evidence("Largest deposit segment / all deposits")
    ds = inp.dataset if isinstance(inp.dataset, BankBalanceSheet) else None
    control, seg_note = C.ADEQUATE, ""
    if ds is not None and ds.deposits:
        i, seg = max(enumerate(ds.deposits), key=lambda kv: kv[1].balance)
        ev += [field_evidence(f"deposits[{i}].balance", f"Balance of segment {seg.segment}."),
               field_evidence(f"deposits[{i}].insured_share", f"Insured share of segment {seg.segment}.")]
        control = (C.STRONG if seg.insured_share >= fd.params["insured_strong"] else
                   C.ADEQUATE if seg.insured_share >= fd.params["insured_adequate"] else C.WEAK)
        seg_note = (f" ({safe_name(seg.segment, 'the largest segment')}, of which {share_words(seg.insured_share)} "
                    f"is insured)")
    rationale = (f"The largest deposit segment{seg_note} is {s.text} of deposits, so one group of depositors "
                 f"can drive a run.")
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def duration_gap(inp: Inputs, fd: FactorDef) -> Outcome:
    gap = inp.require(DQ, "duration_gap_years")
    likelihood = band_up(abs(gap.value), fd.params["gap_cuts"])
    ev = gap.evidence("Duration gap")
    eve = min(inp.grid_refs(RES, "delta_eve_pct_cet1"), key=lambda r: r.value, default=None)
    impact, eve_note = fd.default_impact, ""
    if eve is not None:
        impact = band_up(max(0.0, -eve.value), fd.params["eve_loss_cuts"])
        eve_note = f"; in the worst rate scenario the economic value of equity changes by {eve.text} of CET1"
        ev += eve.evidence("Worst delta EVE / CET1 across the grid")
    hr = inp.metric(DQ, "hedge_ratio")
    if hr is None:
        control = C.ADEQUATE
    else:
        control = (C.STRONG if hr.value >= fd.params["hedge_strong"] else
                   C.ADEQUATE if hr.value >= fd.params["hedge_adequate"] else C.WEAK)
        ev += hr.evidence("Hedge ratio (control)")
    side = "exposed to falling rates" if gap.value < 0 else "exposed to rising rates"
    rationale = f"The duration gap is {gap.text} years, so equity is {side}{eve_note}."
    return Outcome(likelihood, impact, control, rationale, ev)


def hedging(inp: Inputs, fd: FactorDef) -> Outcome:
    hr = inp.require(DQ, "hedge_ratio")
    likelihood = band_down(hr.value, fd.params["ratio_cuts"])
    ev = hr.evidence("Swap notional / fixed-rate securities")
    gap = inp.metric(DQ, "duration_gap_years")
    if gap is not None and abs(gap.value) < fd.params["material_gap_years"]:
        impact, gap_note = fd.params["impact_small_gap"], " and the duration gap is small"
        ev += gap.evidence("Duration gap (impact)")
    else:
        impact, gap_note = fd.default_impact, ""
        if gap is not None:
            ev += gap.evidence("Duration gap (impact)")
    ds = inp.dataset if isinstance(inp.dataset, BankBalanceSheet) else None
    reduced = ds.governance.get("hedges_reduced_last_year") if ds is not None else None
    if reduced is True:
        control, gov = C.WEAK, "; hedges were reduced in the last year"
    elif reduced is False:
        control, gov = C.ADEQUATE, "; hedges were not reduced in the last year"
    else:
        control, gov = C.ADEQUATE, "; whether hedges were reduced is not reported"
    if reduced is not None:
        ev.append(field_evidence("governance.hedges_reduced_last_year", f"Reported as {reduced}."))
    rationale = f"Swaps hedge {hr.text} of fixed-rate securities{gap_note}{gov}."
    return Outcome(likelihood, impact, control, rationale, ev)


def _htm_flips(inp: Inputs) -> tuple[bool, list]:
    """Does any conclusion flip when only the HTM accounting treatment changes?"""
    ev = []
    flips = [f for f in inp.comparison.flips if f.dimension == "htm_treatment"]
    if flips:
        ev.append(comparison_evidence("flips.htm_treatment", flips[0].description))
        return True, ev
    groups: dict[str, list] = {}
    for r in inp.grid(RES):
        key = repr(sorted((k, repr(v)) for k, v in r.spec.params.items() if k != "htm_treatment"))
        groups.setdefault(key, []).append(r)
    for rs in groups.values():
        verdicts = {r.output.labels.get("verdict") for r in rs if r.output}
        if len(verdicts) > 1:
            ev += [label_evidence(r, "verdict") for r in rs]
            return True, ev
    return False, ev


def htm_reliance(inp: Inputs, fd: FactorDef) -> Outcome:
    h = inp.require(DQ, "htm_share_of_securities")
    likelihood = band_up(h.value, fd.params["share_cuts"])
    ev = h.evidence("HTM / all securities")
    flipped, fev = _htm_flips(inp)
    ev += fev
    if flipped:
        impact = fd.params["impact_if_flip"]
        note = ("; the pass/fail verdict flips when unrealised HTM losses are marked to market, so the "
                "conclusion rests on accounting rather than economics")
    else:
        impact = fd.default_impact
        note = "; no verdict depends on the HTM accounting treatment"
        if inp.comparison.flips or inp.grid(RES):
            ev.append(comparison_evidence("flips", "No conclusion flip along htm_treatment."))
    rationale = f"Held-to-maturity securities are {h.text} of the securities book{note}."
    return Outcome(likelihood, impact, C.ADEQUATE, rationale, ev)


def wholesale_dependence(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _bank(inp)
    wholesale = sum(w.amount for w in ds.wholesale_funding)
    funding = wholesale + sum(d.balance for d in ds.deposits)
    if funding <= 0:
        raise MissingInput("deposit or wholesale funding amounts")
    share = wholesale / funding
    likelihood = band_up(share, fd.params["share_cuts"])
    short = [i for i, w in enumerate(ds.wholesale_funding)
             if w.amount > 0 and w.maturity_days <= fd.params["short_maturity_days"]]
    impact = fd.default_impact + (1 if short else 0)
    ev = [field_evidence("wholesale_funding", "Wholesale amounts."), field_evidence("deposits", "Deposit balances.")]
    ev += [field_evidence(f"wholesale_funding[{i}].maturity_days", "Matures within the 30-day stress window.")
           for i in short]
    be = inp.metric(REV, "breakeven_deposit_outflow", where=lambda p: p.get("target") == "liquidity")
    if be is None:
        control, be_note = C.ADEQUATE, ""
    else:
        control = (C.STRONG if be.value >= fd.params["breakeven_strong"] else
                   C.ADEQUATE if be.value >= fd.params["breakeven_adequate"] else C.WEAK)
        be_note = f"; the liquidity constraint breaks at a uniform deposit outflow of {be.text}"
        ev += be.evidence("Liquidity reverse-stress break-even outflow")
    if wholesale <= 0:
        rationale = f"The balance sheet uses no wholesale funding{be_note}."
    else:
        mat = ", some of it maturing within the stress window" if short else ""
        rationale = f"Wholesale funding is {share_words(share)} of total funding{mat}{be_note}."
    return Outcome(likelihood, min(5, impact), control, rationale, ev)


_GOV_SIGNALS = {
    "cro_vacancy_months": "the chief risk officer role has been vacant",
    "board_risk_expertise": "the board lacks risk expertise",
    "risk_committee_meetings_per_year": "the risk committee meets rarely",
    "limit_breaches_last_year": "risk limits were breached in the last year",
    "independent_model_validation": "models are not independently validated",
    "open_supervisory_findings": "supervisory findings are open",
    "hedges_reduced_last_year": "hedges were reduced in the last year",
}


def risk_governance(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _bank(inp)
    g = ds.governance
    known = [k for k in _GOV_SIGNALS if k in g]
    if not known:
        raise MissingInput("governance fields (e.g. governance.cro_vacancy_months); none recognised in the dataset")
    p = fd.params
    score, issues, weak = 0, [], False

    def num(k):
        v = g.get(k)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    if (v := num("cro_vacancy_months")) is not None and v > 0:
        score += 3 if v >= p["cro_vacancy_severe"] else 2 if v >= p["cro_vacancy_material"] else 1
        weak = weak or v >= p["cro_vacancy_material"]
        severity = ("for six months or more" if v >= p["cro_vacancy_severe"] else
                    "for three months or more" if v >= p["cro_vacancy_material"] else "recently")
        issues.append(f"{_GOV_SIGNALS['cro_vacancy_months']} {severity}")
    if g.get("board_risk_expertise") is False:
        score, weak = score + 1, True
        issues.append(_GOV_SIGNALS["board_risk_expertise"])
    if (v := num("risk_committee_meetings_per_year")) is not None and v < p["min_committee_meetings"]:
        score += 1
        issues.append(_GOV_SIGNALS["risk_committee_meetings_per_year"])
    if (v := num("limit_breaches_last_year")) is not None and v > 0:
        score += 2 if v >= p["many_breaches"] else 1
        issues.append(_GOV_SIGNALS["limit_breaches_last_year"])
    if g.get("independent_model_validation") is False:
        score += 1
        issues.append(_GOV_SIGNALS["independent_model_validation"])
    if (v := num("open_supervisory_findings")) is not None and v > 0:
        score += 1
        issues.append(_GOV_SIGNALS["open_supervisory_findings"])
    if g.get("hedges_reduced_last_year") is True:
        score += 1
        issues.append(_GOV_SIGNALS["hedges_reduced_last_year"])
    likelihood = min(5, 1 + score)
    control = C.WEAK if weak else (C.STRONG if not issues and len(known) >= p["strong_min_fields"] else C.ADEQUATE)
    ev = [field_evidence(f"governance.{k}", f"Reported as {g[k]!r}.") for k in known]
    if issues:
        rationale = "Governance evidence shows that " + "; ".join(issues) + "."
    else:
        rationale = (f"None of the {count_words(len(known))} reported governance indicators shows a weakness.")
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def credit_concentration(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _bank(inp)
    total = sum(p.ead for p in ds.loan_pools)
    if not ds.loan_pools or total <= 0:
        raise MissingInput("loan pools with positive EAD")
    i, pool = max(enumerate(ds.loan_pools), key=lambda kv: kv[1].ead)
    share = pool.ead / total
    likelihood = band_up(share, fd.params["share_cuts"])
    impact = fd.default_impact + (1 if pool.pd >= fd.params["high_pd"] else 0)
    ev = [field_evidence(f"loan_pools[{i}].ead", f"EAD of pool {pool.segment}."),
          field_evidence(f"loan_pools[{i}].pd", f"PD of pool {pool.segment}."),
          field_evidence("loan_pools", "All pool EADs (denominator).")]
    gap = inp.metric(DQ, "loan_reconciliation_gap")
    control, rec = C.ADEQUATE, ""
    if gap is not None:
        ev += gap.evidence("Loan reconciliation gap (control)")
        if gap.value >= fd.params["recon_gap_weak"]:
            control = C.WEAK
            rec = f"; loan-pool EAD does not reconcile to the loan book (gap {gap.text})"
    name = safe_name(pool.segment, "the largest pool")
    riskier = " and is among the riskier pools" if pool.pd >= fd.params["high_pd"] else ""
    rationale = (f"The largest loan pool ({name}) carries {share_words(share)} of exposure at default"
                 f"{riskier}{rec}.")
    return Outcome(likelihood, min(5, impact), control, rationale, ev)


RUBRIC: tuple[FactorDef, ...] = (
    FactorDef(
        "uninsured_deposits", "Uninsured deposits",
        "Share of deposits without deposit insurance (run-prone funding).", 4, uninsured_deposits,
        inputs=("q2.data_quality: uninsured_deposit_share, hqla_share",
                "q2.resilience grid: verdict / binding_constraint under fast runs"),
        control_basis="HQLA buffer: strong >= 20% of assets, adequate >= 10%, weak below.",
        params={"share_cuts": (0.20, 0.35, 0.50, 0.70), "impact_if_fast_run_fails": 5,
                "hqla_strong": 0.20, "hqla_adequate": 0.10},
    ),
    FactorDef(
        "deposit_concentration", "Deposit concentration",
        "Dependence on the largest deposit segment.", 4, deposit_concentration,
        inputs=("q2.data_quality: largest_segment_share", "dataset.deposits[*].balance / insured_share"),
        control_basis="Insured share of the largest segment: strong >= 75%, adequate >= 40%, weak below.",
        params={"share_cuts": (0.15, 0.25, 0.40, 0.60), "insured_strong": 0.75, "insured_adequate": 0.40},
    ),
    FactorDef(
        "duration_gap", "Duration gap (IRRBB)",
        "Mismatch between asset and liability duration and the resulting EVE sensitivity.", 4, duration_gap,
        inputs=("q2.data_quality: duration_gap_years, hedge_ratio", "q2.resilience grid: delta_eve_pct_cet1"),
        control_basis="Hedge ratio: strong >= 50%, adequate >= 20%, weak below.",
        params={"gap_cuts": (1.0, 2.0, 3.0, 5.0), "eve_loss_cuts": (0.05, 0.10, 0.15, 0.30),
                "hedge_strong": 0.50, "hedge_adequate": 0.20},
    ),
    FactorDef(
        "hedging", "Interest-rate hedging",
        "How much of the fixed-rate securities book is hedged with swaps.", 4, hedging,
        inputs=("q2.data_quality: hedge_ratio, duration_gap_years", "dataset.governance.hedges_reduced_last_year"),
        control_basis="Weak if hedges were reduced in the last year, else adequate.",
        params={"ratio_cuts": (0.50, 0.30, 0.15, 0.05), "material_gap_years": 2.0, "impact_small_gap": 2},
    ),
    FactorDef(
        "htm_reliance", "Reliance on HTM accounting",
        "Share of securities held to maturity, whose losses are hidden from capital at cost.", 3, htm_reliance,
        inputs=("q2.data_quality: htm_share_of_securities", "comparison.flips (dimension htm_treatment)"),
        control_basis="No control evidence in the data: adequate by default.",
        params={"share_cuts": (0.10, 0.25, 0.40, 0.60), "impact_if_flip": 5},
    ),
    FactorDef(
        "wholesale_dependence", "Wholesale funding dependence",
        "Share of funding from wholesale markets, which can vanish in stress.", 3, wholesale_dependence,
        inputs=("dataset.wholesale_funding[*].amount / maturity_days", "dataset.deposits[*].balance",
                "q2.reverse_stress (liquidity): breakeven_deposit_outflow"),
        control_basis="Liquidity break-even outflow: strong >= 30%, adequate >= 15%, weak below.",
        params={"share_cuts": (0.05, 0.10, 0.20, 0.30), "short_maturity_days": 30,
                "breakeven_strong": 0.30, "breakeven_adequate": 0.15},
    ),
    FactorDef(
        "risk_governance", "Risk governance",
        "Quality of risk oversight (CRO, board, committees, limits, validation).", 4, risk_governance,
        inputs=tuple(f"dataset.governance.{k}" for k in _GOV_SIGNALS),
        control_basis="Weak if the CRO seat has been vacant three months or more or the board lacks risk "
                      "expertise; strong if at least three indicators are reported and none is adverse.",
        params={"cro_vacancy_severe": 6, "cro_vacancy_material": 3, "min_committee_meetings": 4,
                "many_breaches": 5, "strong_min_fields": 3},
    ),
    FactorDef(
        "credit_concentration", "Credit concentration",
        "Dependence of credit losses on the largest loan pool.", 3, credit_concentration,
        inputs=("dataset.loan_pools[*].ead / pd", "q2.data_quality: loan_reconciliation_gap"),
        control_basis="Weak if loan pools do not reconcile to the loan book (gap >= 5%), else adequate.",
        params={"share_cuts": (0.25, 0.35, 0.50, 0.70), "high_pd": 0.03, "recon_gap_weak": 0.05},
    ),
)
