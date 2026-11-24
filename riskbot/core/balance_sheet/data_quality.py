"""``q2.data_quality``: reconciliation and structural indicators used by the Q2 rubric.

Metrics (all fractions unless stated):

* loan_reconciliation_gap = |Σ EAD − loans book| / loans book
* uninsured_deposit_share = Σ D_s(1 − ι_s) / Σ D_s
* largest_segment_share = max_s D_s / Σ D_s
* hqla_share = market value of HQLA assets (cash, HQLA securities, other assets with a level) / total MV
* duration_gap_years = D_A − (L / A) D_L with MV-weighted asset modified duration D_A, total asset MV A,
  liabilities L = deposits + wholesale and amount-weighted liability duration D_L (deposit 2(1 − β),
  wholesale days/365) — the classic duration gap (Bierwag; Saunders & Cornett)
* hedge_ratio = pay-fixed swap notional / market value of fixed-rate securities
  (fixed-rate: repricing_years >= maturity_years > 0)
* htm_share_of_securities = HTM market value / all securities' market value

Quality label: ``poor`` if the gap exceeds 10% or any error finding exists; ``fair`` if any warning; else
``good``. Thresholds are illustrative.
"""

from __future__ import annotations

from typing import Any

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import BankBalanceSheet, DataQualityFinding, ModelOutput, ModelSpec, Severity, Unit

from . import engine
from .validation import check_structure, coerce_balance_sheet, loans_book, reconciliation_gap

GAP_WARNING, GAP_ERROR = 0.02, 0.10
UNINSURED_WARNING = 0.50
SEGMENT_WARNING = 0.40
UNHEDGED_FIXED_SHARE = 0.20
THIN_HEDGE_RATIO = 0.25
DURATION_GAP_WARNING = 3.0
DEPOSIT_GROWTH_WARNING = 0.50

ASSUMPTIONS = [
    "All thresholds (2%/10% reconciliation, 50% uninsured, 40% single segment, 20% unhedged fixed-rate "
    "securities, 25% thin hedge ratio, 3-year duration gap, 50% two-year deposit growth) are illustrative.",
    "Durations as in q2.resilience (par-bond derivation, deposits 2 x (1 - beta), wholesale days/365).",
    "Shares of securities and HQLA use market values; the loan reconciliation uses book values.",
]


def _ratio(n: float, d: float) -> float:
    return n / d if d > 0 else 0.0


class DataQualityModel:
    spec: ModelSpec = catalog.Q2_DATA_QUALITY

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:  # noqa: C901
        mid = self.spec.model_id
        bs: BankBalanceSheet = coerce_balance_sheet(dataset, mid)
        eff = resolve_params(self.spec, params)
        check_structure(bs, mid, for_stress=False)
        h = model_input_hash(mid, bs, eff, seed)
        tb = TraceBuilder(mid, f"{self.spec.title}: {bs.name}", h, assumptions=ASSUMPTIONS,
                          inputs={"n_assets": len(bs.assets), "n_loan_pools": len(bs.loan_pools),
                                  "n_deposit_segments": len(bs.deposits), "synthetic": bs.synthetic})
        findings: list[DataQualityFinding] = []
        F, Y = Unit.FRACTION, Unit.YEARS

        def add(check: str, sev: Severity, fld: str, msg: str, subject: str | None = None, count: int = 0) -> None:
            findings.append(DataQualityFinding(check=check, severity=sev, field=fld, subject=subject, count=count,
                                               message=msg))

        # Reconciliation
        book, ead = loans_book(bs), sum(p.ead for p in bs.loan_pools)
        gap = reconciliation_gap(bs)
        tb.step("loan_reconciliation_gap", "Loan-pool reconciliation", r"\left|\sum EAD - B_{loans}\right| / B_{loans}",
                f"|{ead:,.0f} - {book:,.0f}| / {book:,.0f} = {gap:.6f}", value=gap, unit=F,
                table=[{"segment": p.segment, "ead": p.ead} for p in bs.loan_pools] or None)
        if gap > GAP_ERROR:
            add("loan_reconciliation_gap", Severity.ERROR, "loan_pools", f"Loan pools differ from the loan book by "
                f"{gap:.1%} (> {GAP_ERROR:.0%}).", count=len(bs.loan_pools))
        elif gap > GAP_WARNING:
            add("loan_reconciliation_gap", Severity.WARNING, "loan_pools", f"Loan pools differ from the loan book by "
                f"{gap:.1%} (> {GAP_WARNING:.0%}).", count=len(bs.loan_pools))

        # Deposits
        dep = sum(d.balance for d in bs.deposits)
        unins = sum(d.balance * (1 - d.insured_share) for d in bs.deposits)
        u_share = _ratio(unins, dep)
        tb.step("uninsured_deposit_share", "Uninsured deposit share", r"\sum_s D_s(1-\iota_s) / \sum_s D_s",
                f"{unins:,.0f} / {dep:,.0f} = {u_share:.6f}", value=u_share, unit=F,
                table=[{"segment": d.segment, "balance": d.balance, "insured_share": d.insured_share,
                        "uninsured": d.balance * (1 - d.insured_share)} for d in bs.deposits] or None)
        if u_share > UNINSURED_WARNING:
            add("uninsured_share_high", Severity.WARNING, "deposits.insured_share",
                f"Uninsured deposits are {u_share:.1%} of deposits (> {UNINSURED_WARNING:.0%}).")
        largest = max(bs.deposits, key=lambda d: d.balance) if bs.deposits else None
        l_share = _ratio(largest.balance, dep) if largest else 0.0
        tb.step("largest_segment_share", "Largest deposit segment", r"\max_s D_s / \sum_s D_s",
                f"{(largest.balance if largest else 0):,.0f} / {dep:,.0f} = {l_share:.6f}"
                + (f" ({largest.segment})" if largest else ""), value=l_share, unit=F)
        if l_share > SEGMENT_WARNING and largest:
            add("deposit_concentration", Severity.WARNING, "deposits.balance",
                f"Segment {largest.segment} holds {l_share:.1%} of deposits (> {SEGMENT_WARNING:.0%}).",
                subject=largest.segment)
        if not bs.deposits:
            add("no_deposits", Severity.WARNING, "deposits", "No deposit segments supplied.")

        # Assets, HQLA, durations
        a_mv = sum(a.market_value for a in bs.assets)
        hq = sum(a.market_value for a in bs.assets if engine.hqla_level(a) is not None)
        hq_share = _ratio(hq, a_mv)
        tb.step("hqla_share", "HQLA share of assets", r"\sum_{j \in HQLA} MV_j / \sum_j MV_j",
                f"{hq:,.0f} / {a_mv:,.0f} = {hq_share:.6f}", value=hq_share, unit=F,
                note="Before LCR haircuts.")
        risk = [(a, *engine.asset_risk(a, bs.policy_rate)) for a in bs.assets]
        d_a = _ratio(sum(a.market_value * d for a, _, _, d, _, _ in risk), a_mv)
        liab = [(d.balance, engine.deposit_duration(d.rate_beta)) for d in bs.deposits] + \
            [(w.amount, w.maturity_days / 365.0) for w in bs.wholesale_funding]
        l_tot = sum(x for x, _ in liab)
        d_l = _ratio(sum(x * d for x, d in liab), l_tot)
        dgap = d_a - _ratio(l_tot, a_mv) * d_l
        tb.step("duration_gap_years", "Duration gap", r"D_A - \frac{L}{A} D_L",
                f"{d_a:.4f} - ({l_tot:,.0f} / {a_mv:,.0f}) x {d_l:.4f} = {dgap:.6f}", value=dgap, unit=Y,
                table=[{"id": a.id, "market_value": a.market_value, "modified_duration": round(d, 6), "source": src}
                       for a, _, _, d, _, src in risk])
        if dgap > DURATION_GAP_WARNING:
            add("duration_gap_high", Severity.WARNING, "assets", f"Duration gap of {dgap:.2f} years "
                f"(> {DURATION_GAP_WARNING:g}).")

        # Hedging
        secs = [a for a in bs.assets if a.kind in engine.SECURITY_KINDS]
        fixed = [a for a in secs if a.maturity_years > 0 and a.repricing_years >= a.maturity_years]
        fixed_mv = sum(a.market_value for a in fixed)
        notional = sum(hd.notional for hd in bs.hedges if hd.pay_fixed)
        hr = _ratio(notional, fixed_mv)
        tb.step("hedge_ratio", "Hedge ratio", r"\sum N^{pay\ fixed} / \sum_{\text{fixed-rate sec.}} MV",
                f"{notional:,.0f} / {fixed_mv:,.0f} = {hr:.6f}", value=hr, unit=F,
                note="0 when there are no fixed-rate securities.")
        fixed_share = _ratio(fixed_mv, a_mv)
        if not bs.hedges and fixed_share > UNHEDGED_FIXED_SHARE:
            add("unhedged_fixed_rate_securities", Severity.WARNING, "hedges",
                f"No hedges while fixed-rate securities are {fixed_share:.1%} of assets (> {UNHEDGED_FIXED_SHARE:.0%}).")
        elif bs.hedges and fixed_mv > 0 and hr < THIN_HEDGE_RATIO:
            add("thin_hedging", Severity.WARNING, "hedges",
                f"Swap notional covers {hr:.1%} of fixed-rate securities (< {THIN_HEDGE_RATIO:.0%}).")
        htm = sum(a.market_value for a in secs if a.kind == "htm_securities")
        sec_mv = sum(a.market_value for a in secs)
        htm_share = _ratio(htm, sec_mv)
        tb.step("htm_share_of_securities", "HTM share of securities", r"MV_{HTM} / MV_{securities}",
                f"{htm:,.0f} / {sec_mv:,.0f} = {htm_share:.6f}", value=htm_share, unit=F)

        # Item-level plausibility
        for a in bs.assets:
            if a.book_value > 0 and a.market_value == 0:
                add("zero_market_value", Severity.ERROR, f"assets[{a.id}].market_value",
                    f"Asset {a.id} has book value but zero market value.", subject=a.id)
            if a.repricing_years > a.maturity_years:
                add("repricing_after_maturity", Severity.WARNING, f"assets[{a.id}].repricing_years",
                    f"Asset {a.id} reprices after it matures.", subject=a.id)
            if a.kind in ("hqla_securities",) and a.hqla_level is None:
                add("hqla_level_missing", Severity.WARNING, f"assets[{a.id}].hqla_level",
                    f"HQLA security {a.id} has no level; treated as level 1.", subject=a.id)
            if a.kind in engine.SECURITY_KINDS and a.book_value > 0 and a.market_value < 0.85 * a.book_value:
                add("large_embedded_loss", Severity.INFO, f"assets[{a.id}].market_value",
                    f"{a.id} trades at {a.market_value / a.book_value:.1%} of book.", subject=a.id)
        for d in bs.deposits:
            if d.runoff_fast < d.runoff_slow:
                add("runoff_order", Severity.ERROR, f"deposits[{d.segment}].runoff_fast",
                    f"Fast run-off below slow run-off for {d.segment}.", subject=d.segment)
        a_book = sum(a.book_value for a in bs.assets)
        implied_equity = a_book - l_tot
        if implied_equity < bs.cet1_capital:
            add("equity_below_cet1", Severity.WARNING, "cet1_capital",
                f"Assets minus modelled liabilities ({implied_equity:,.0f}) are below CET1 ({bs.cet1_capital:,.0f}).")

        # Governance evidence
        g = bs.governance
        if isinstance(g.get("cro_vacancy_months"), (int, float)) and not isinstance(g["cro_vacancy_months"], bool) \
                and g["cro_vacancy_months"] > 0:
            add("cro_vacancy", Severity.WARNING, "governance.cro_vacancy_months",
                f"Chief risk officer post vacant for {g['cro_vacancy_months']} months.")
        if g.get("hedges_reduced_last_year") is True:
            add("hedges_reduced", Severity.WARNING, "governance.hedges_reduced_last_year",
                "Interest-rate hedges were reduced in the last year.")
        growth = g.get("deposit_growth_2y")
        if isinstance(growth, (int, float)) and not isinstance(growth, bool) and growth > DEPOSIT_GROWTH_WARNING:
            add("rapid_deposit_growth", Severity.WARNING, "governance.deposit_growth_2y",
                f"Deposits grew {growth:.0%} in two years (> {DEPOSIT_GROWTH_WARNING:.0%}).")

        if gap > GAP_ERROR or any(f.severity == Severity.ERROR for f in findings):
            quality = "poor"
        elif any(f.severity == Severity.WARNING for f in findings):
            quality = "fair"
        else:
            quality = "good"
        tb.step("quality", "Quality label", r"\text{poor if gap} > 10\% \text{ or error; fair if warning; else good}",
                f"{sum(f.severity == Severity.ERROR for f in findings)} errors, "
                f"{sum(f.severity == Severity.WARNING for f in findings)} warnings -> {quality}",
                table=[{"check": f.check, "severity": f.severity.value, "subject": f.subject, "message": f.message}
                       for f in findings] or None)
        values = {"loan_reconciliation_gap": (gap, F), "uninsured_deposit_share": (u_share, F),
                  "largest_segment_share": (l_share, F), "hqla_share": (hq_share, F),
                  "duration_gap_years": (dgap, Y), "hedge_ratio": (hr, F), "htm_share_of_securities": (htm_share, F)}
        metrics = {k: tb.metric(k, v, u) for k, (v, u) in values.items()}
        return ModelOutput(model_id=mid, params=eff, metrics=metrics, labels={"quality": quality},
                           traces=[tb.build({k: v for k, (v, _) in values.items()})], findings=findings,
                           warnings=tb.warnings)
