"""``q2.resilience``: instantaneous parallel rate shock plus a 30-day deposit run.

Turns ``engine.evaluate`` into a ``ModelOutput`` with one trace step per intermediate quantity
(formula in LaTeX, numbers substituted, per-item tables). See README.md for the full documentation.
"""

from __future__ import annotations

from typing import Any

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import BankBalanceSheet, DataQualityFinding, ModelOutput, ModelSpec, Severity, Unit

from . import engine
from .validation import check_structure, coerce_balance_sheet, reconciliation_gap

ASSUMPTIONS = [
    "Instantaneous parallel shift of all rates; no curve twists, basis or spread risk.",
    "Durations without a given value are derived for an annual-coupon bullet bond priced at par (yield = coupon; "
    "zero-coupon instruments are discounted at the policy rate); the maturity used is the time to next repricing "
    "capped at final maturity. Cash has zero duration. A given duration without convexity gets the convexity of "
    "the zero-coupon bond with that duration.",
    "Value changes use the second-order approximation dV = MV(-D dy + C dy^2 / 2).",
    "Non-maturity deposits have an effective duration of 2 years x (1 - rate beta) (illustrative); wholesale "
    "duration = maturity_days / 365; liability convexity is ignored.",
    "Swaps: value change of a pay-fixed swap = notional x D x dy with D the modified duration of a par bond at the "
    "fixed rate; the floating leg reprices immediately.",
    "NII: static balance sheet over 12 months; items repricing within a year earn dy for the remaining part of the "
    "year; deposits reprice at once by beta x dy; NII is reported but does not change capital.",
    "Credit loss = sum EAD x LGD x Vasicek stressed PD at q = 0.90 (base) or 0.99 (adverse); one-year horizon, "
    "LGD not stressed, losses recognised immediately against CET1.",
    "Run: deposits leave at the segment's 30-day run-off rate; in slow/fast runs wholesale funding maturing within "
    "30 days is not rolled over; with run_speed none nothing leaves.",
    "Outflows are met from cash, then HQLA securities sold pro rata at post-shock market value, then AFS, then HTM "
    "securities at the fire-sale price exp(-lambda s), s = share of the post-shock AFS+HTM market value sold.",
    "Accounting: HQLA and AFS securities are carried at fair value and their pre-shock marks are already in CET1; "
    "HTM securities are carried at book (amortised) value. Realised loss = carrying value of the securities sold "
    "(pro rata) - proceeds, so selling HTM crystallises its embedded loss. Remaining HQLA/AFS securities charge "
    "their shock loss; remaining HTM securities charge book - post-shock market value only under mark_to_market.",
    "Loans, other assets and liabilities stay at book value for capital; ΔEVE is reported, not deducted.",
    "RWA unchanged by the stress; capital ratio = CET1 / RWA.",
    "LCR (illustrative): HQLA haircuts level 1 0%, 2a 15%, 2b 50% (no level-2 caps), deposit run-off 5% insured / "
    "25% uninsured, 100% of wholesale maturing within 30 days, no inflows. After the run: remaining HQLA at "
    "post-shock value over outflows on the remaining deposits (wholesale already repaid in slow/fast runs). "
    "LCR is capped at 100 and is 0 if a liquidity shortfall remains.",
    "Thresholds, run-off rates, haircuts and the deposit duration rule are illustrative and are not any "
    "jurisdiction's rules.",
]


def _fmt(x: float) -> str:
    return f"{x:,.0f}"


def reconciliation_findings(bs: BankBalanceSheet) -> list[DataQualityFinding]:
    gap = reconciliation_gap(bs)
    if gap <= 0.02:
        return []
    sev = Severity.ERROR if gap > 0.10 else Severity.WARNING
    return [DataQualityFinding(check="loan_reconciliation_gap", severity=sev, field="loan_pools",
                               count=len(bs.loan_pools),
                               message=f"Loan-pool EAD differs from the loan book by {gap:.1%} (> 2%).")]


def scenario_from_params(p: dict[str, Any]) -> engine.Scenario:
    return engine.Scenario(
        rate_shock_bp=float(p["rate_shock_bp"]), run_speed=p["run_speed"], loss_severity=p["loss_severity"],
        htm_treatment=p["htm_treatment"], capital_threshold=p["capital_threshold"],
        lcr_threshold=p["lcr_threshold"], fire_sale_impact=p["fire_sale_impact"])


def _r(x: float, nd: int = 6) -> float:
    return float(round(x, nd))


class ResilienceModel:
    spec: ModelSpec = catalog.Q2_RESILIENCE

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        mid = self.spec.model_id
        bs = coerce_balance_sheet(dataset, mid)
        eff = resolve_params(self.spec, params)
        check_structure(bs, mid, for_stress=True)
        sc = scenario_from_params(eff)
        res = engine.evaluate(bs, sc)
        h = model_input_hash(mid, bs, eff, seed)
        tb = TraceBuilder(mid, f"{self.spec.title}: {bs.name}", h, assumptions=ASSUMPTIONS, inputs={
            "params": eff, "n_assets": len(bs.assets), "n_loan_pools": len(bs.loan_pools),
            "n_deposit_segments": len(bs.deposits), "n_wholesale": len(bs.wholesale_funding),
            "n_hedges": len(bs.hedges), "cet1_capital": bs.cet1_capital, "rwa": bs.risk_weighted_assets,
            "policy_rate": bs.policy_rate, "synthetic": bs.synthetic})
        build_trace(tb, bs, res)
        for w in res.warnings:
            tb.warn(w)
        C, F, R = Unit.CURRENCY, Unit.FRACTION, Unit.RATIO
        values = {
            "delta_eve": (res.delta_eve, C), "delta_eve_pct_cet1": (res.delta_eve_pct_cet1, F),
            "delta_nii_12m": (res.delta_nii_12m, C), "credit_loss": (res.credit_loss, C),
            "unrealised_securities_loss": (res.unrealised_securities_loss, C),
            "deposit_outflow": (res.deposit_outflow, C), "fire_sale_loss": (res.fire_sale_loss, C),
            "cet1_after": (res.cet1_after, C), "capital_ratio_before": (res.capital_ratio_before, F),
            "capital_ratio_after": (res.capital_ratio_after, F), "lcr_before": (res.lcr_before, R),
            "lcr_after": (res.lcr_after, R),
        }
        metrics = {k: tb.metric(k, v, u) for k, (v, u) in values.items()}
        trace = tb.build({k: v for k, (v, _) in values.items()})
        return ModelOutput(model_id=mid, params=eff, metrics=metrics,
                           labels={"verdict": res.verdict, "binding_constraint": res.binding_constraint},
                           traces=[trace], findings=reconciliation_findings(bs), warnings=list(res.warnings))


def build_trace(tb: TraceBuilder, bs: BankBalanceSheet, res: engine.StressResult) -> None:  # noqa: C901
    sc = res.scenario
    C, F, R, Y = Unit.CURRENCY, Unit.FRACTION, Unit.RATIO, Unit.YEARS
    dy = sc.dy
    tb.step("rate_shock", "Parallel rate shock", r"\Delta y = \text{shock}_{bp} / 10\,000",
            f"Δy = {sc.rate_shock_bp:g} / 10000 = {dy:.4f}", value=dy, unit=F)

    tb.step("asset_durations", "Asset duration and convexity",
            r"D_{mod} = \frac{1}{(1+y)P}\sum_i t_i CF_i (1+y)^{-t_i},\quad "
            r"C = \frac{1}{P}\sum_i t_i(t_i+1) CF_i (1+y)^{-t_i-2}",
            "Annual-coupon bullet bond at par (y = coupon) over T = min(repricing, maturity); see table.",
            table=[{"id": r.id, "kind": r.kind, "market_value": r.mv, "T_years": r.t_dur, "yield": r.y,
                    "modified_duration": _r(r.dmod), "convexity": _r(r.conv), "source": r.source}
                   for r in res.assets])
    a_mv = sum(r.mv for r in res.assets)
    d_a = sum(r.mv * r.dmod for r in res.assets) / a_mv
    tb.step("asset_duration_avg", "Market-value-weighted asset duration", r"D_A = \sum_j MV_j D_j / \sum_j MV_j",
            f"D_A = {_fmt(sum(r.mv * r.dmod for r in res.assets))} / {_fmt(a_mv)} = {d_a:.4f}", value=d_a, unit=Y)
    tb.step("delta_assets", "Change in asset value",
            r"\Delta A = \sum_j MV_j\left(-D_j\Delta y + \tfrac12 C_j \Delta y^2\right)",
            " + ".join(f"{_fmt(r.dv)}" for r in res.assets) + f" = {_fmt(res.delta_assets)}",
            value=res.delta_assets, unit=C,
            table=[{"id": r.id, "market_value": r.mv, "delta_value": r.dv, "market_value_after": r.mv_post}
                   for r in res.assets])
    tb.step("delta_liabilities", "Change in liability value",
            r"\Delta L = -\sum_k L_k D_k \Delta y,\quad D_{dep} = 2(1-\beta),\ D_{wh} = \text{days}/365",
            " + ".join(_fmt(x["delta_value"]) for x in res.liabilities) + f" = {_fmt(res.delta_liabilities)}",
            value=res.delta_liabilities, unit=C, table=[dict(x) for x in res.liabilities])
    tb.step("delta_swaps", "Change in value of swap hedges",
            r"\Delta S = \sum_h \pm N_h D^{swap}_h \Delta y \quad (+\text{ pay fixed})",
            (" + ".join(_fmt(x["delta_value"]) for x in res.swaps) or "0") + f" = {_fmt(res.delta_swaps)}",
            value=res.delta_swaps, unit=C, table=[dict(x) for x in res.swaps] or None)
    tb.step("delta_eve", "Change in economic value of equity", r"\Delta EVE = \Delta A - \Delta L + \Delta S",
            f"{_fmt(res.delta_assets)} - ({_fmt(res.delta_liabilities)}) + {_fmt(res.delta_swaps)} = "
            f"{_fmt(res.delta_eve)}", value=res.delta_eve, unit=C)
    tb.step("delta_eve_pct_cet1", "ΔEVE as a share of CET1", r"\Delta EVE / CET1",
            f"{_fmt(res.delta_eve)} / {_fmt(bs.cet1_capital)} = {res.delta_eve_pct_cet1:.4f}",
            value=res.delta_eve_pct_cet1, unit=F)

    tb.step("nii_assets", "NII change from assets repricing within 12 months",
            r"\Delta NII_A = \sum_{j: \tau_j < 1} B_j \Delta y (1 - \tau_j)",
            f"= {_fmt(res.nii_assets)}", value=res.nii_assets, unit=C,
            table=[dict(x) for x in res.nii_rows if x["side"] == "asset"] or None)
    tb.step("nii_liabilities", "Funding-cost change over 12 months",
            r"\Delta NII_L = \sum_s D_s \beta_s \Delta y + \sum_{w: m_w<365} W_w \Delta y (1 - m_w/365)",
            f"= {_fmt(res.nii_liabilities)}", value=res.nii_liabilities, unit=C,
            table=[dict(x) for x in res.nii_rows if x["side"] in ("deposit", "wholesale")] or None)
    tb.step("nii_swaps", "Net floating receipts on swaps", r"\Delta NII_S = \sum_h \pm N_h \Delta y",
            f"= {_fmt(res.nii_swaps)}", value=res.nii_swaps, unit=C)
    tb.step("delta_nii_12m", "12-month NII change", r"\Delta NII = \Delta NII_A - \Delta NII_L + \Delta NII_S",
            f"{_fmt(res.nii_assets)} - {_fmt(res.nii_liabilities)} + {_fmt(res.nii_swaps)} = "
            f"{_fmt(res.delta_nii_12m)}", value=res.delta_nii_12m, unit=C,
            note="Reported only; NII does not change capital in this model.")

    q = engine.VASICEK_Q[sc.loss_severity]
    tb.step("credit_loss", "Stressed credit loss",
            r"CL = \sum_p EAD_p\,LGD_p\,\Phi\!\left(\frac{\Phi^{-1}(PD_p) + \sqrt{\rho_p}\,\Phi^{-1}(q)}"
            r"{\sqrt{1-\rho_p}}\right)",
            f"q = {q}: " + " + ".join(_fmt(x["loss"]) for x in res.credit_rows) + f" = {_fmt(res.credit_loss)}",
            value=res.credit_loss, unit=C,
            table=[{k: (_r(v, 8) if isinstance(v, float) and k != "ead" and k != "loss" else v)
                    for k, v in x.items()} for x in res.credit_rows] or None)
    tb.step("unrealised_securities_loss", "Shock loss on securities (before sales)",
            r"UL = -\sum_{j \in \text{HQLA, AFS, HTM}} \Delta V_j",
            f"= {_fmt(res.unrealised_securities_loss)}", value=res.unrealised_securities_loss, unit=C,
            table=[dict(x) for x in res.securities_rows] or None,
            note="Positive = loss. Pre-shock embedded losses against book are shown per security but are not "
                 "part of this figure.")

    run_desc = f"uniform {sc.uniform_outflow:.4f}" if sc.run_speed == "uniform" else sc.run_speed
    tb.step("deposit_outflow", "30-day deposit outflow", r"O_D = \sum_s D_s r_s",
            f"run = {run_desc}: " + " + ".join(_fmt(x["outflow"]) for x in res.outflow_rows) +
            f" = {_fmt(res.deposit_outflow)}", value=res.deposit_outflow, unit=C,
            table=[dict(x) for x in res.outflow_rows] or None)
    tb.step("wholesale_outflow", "Wholesale funding not rolled over",
            r"O_W = \sum_{w:\ m_w \le 30} W_w \ \text{(slow/fast runs only)}",
            f"= {_fmt(res.wholesale_outflow)}", value=res.wholesale_outflow, unit=C)
    tb.step("liquidity_need", "Total 30-day liquidity need", r"N = O_D + O_W",
            f"{_fmt(res.deposit_outflow)} + {_fmt(res.wholesale_outflow)} = {_fmt(res.total_need)}",
            value=res.total_need, unit=C)
    tb.step("cash_used", "Cash used", r"U_{cash} = \min(N, \text{cash})",
            f"min({_fmt(res.total_need)}, {_fmt(res.cash_available)}) = {_fmt(res.cash_used)}",
            value=res.cash_used, unit=C)
    tb.step("hqla_securities_sold", "HQLA securities sold at post-shock value",
            r"U_{HQLA} = \min(N - U_{cash},\ \textstyle\sum MV^{post}_{HQLA})",
            f"min({_fmt(res.total_need - res.cash_used)}, {_fmt(res.hqla_sec_pool)}) = {_fmt(res.hqla_sec_sold)}; "
            f"realised loss = carrying sold - proceeds = {_fmt(res.hqla_sale_loss)}",
            value=res.hqla_sec_sold, unit=C)
    fs = res.fire_sale
    rem = res.total_need - res.cash_used - res.hqla_sec_sold
    tb.step("fire_sale_pool", "Saleable AFS + HTM pool (post-shock market value)", r"S = \sum MV^{post}_{AFS+HTM}",
            f"S = {_fmt(res.saleable_pool)}; remaining need = {_fmt(rem)}", value=res.saleable_pool, unit=C)
    tb.step("fire_sale_iterations", "Fire-sale fixed point",
            r"s_{k+1} = \frac{N'}{S} e^{\lambda s_k},\quad s_0 = 0 \;\Rightarrow\; s^* S e^{-\lambda s^*} = N'",
            f"λ = {sc.fire_sale_impact:g}, N' = {_fmt(rem)}, S = {_fmt(res.saleable_pool)}: method = {fs.method}, "
            f"{max(0, len(fs.iterations) - 1)} iterations, s* = {fs.share:.8f}",
            value=fs.share, unit=F,
            table=[{"k": k, "s_k": _r(s, 12), "proceeds": p} for k, s, p in fs.iterations] or None,
            note="sell_all: the need exceeds the maximum proceeds S e^{-λ}; everything is sold." if
            fs.method == "sell_all" else "")
    tb.step("fire_sale_price", "Fire-sale price factor", r"p = e^{-\lambda s^*}",
            f"exp(-{sc.fire_sale_impact:g} x {fs.share:.6f}) = {fs.price:.6f}", value=fs.price, unit=F)
    tb.step("fire_sale_proceeds", "Fire-sale proceeds", r"P = s^* S p",
            f"{fs.share:.6f} x {_fmt(res.saleable_pool)} x {fs.price:.6f} = {_fmt(fs.proceeds)}",
            value=fs.proceeds, unit=C)
    tb.step("liquidity_shortfall", "Liquidity shortfall", r"\max(0,\ N' - S e^{-\lambda})",
            f"= {_fmt(res.liquidity_shortfall)}", value=res.liquidity_shortfall, unit=C)
    tb.step("fire_sale_loss", "Realised loss on forced sales",
            r"RL = \sum_{\text{sold}} f_j \cdot \text{carrying}_j - \text{proceeds}",
            f"HQLA {_fmt(res.hqla_sale_loss)} + AFS/HTM ({_fmt(res.fire_sale_carrying_sold)} - {_fmt(fs.proceeds)}) "
            f"= {_fmt(res.fire_sale_loss)}", value=res.fire_sale_loss, unit=C,
            table=[{"id": r.id, "kind": r.kind, "sold_share": _r(r.sold_share, 8), "carrying": r.carrying}
                   for r in res.assets if r.kind in engine.SECURITY_KINDS])

    tb.step("unrealised_charge_fair_value", "Shock loss on remaining HQLA and AFS securities",
            r"\sum_{j \in HQLA,AFS} (1-f_j)(\text{carrying}_j - MV^{post}_j)",
            f"= {_fmt(res.unrealised_charge_fv)}", value=res.unrealised_charge_fv, unit=C)
    tb.step("unrealised_charge_htm", "Unrealised loss on remaining HTM securities",
            r"\mathbb{1}_{MTM}\sum_{j \in HTM} (1-f_j)(B_j - MV^{post}_j)",
            f"htm_treatment = {sc.htm_treatment}: {_fmt(res.unrealised_charge_htm)}",
            value=res.unrealised_charge_htm, unit=C)
    tb.step("cet1_after", "CET1 after stress", r"CET1' = CET1 - CL - RL - UL_{FV} - UL_{HTM}",
            f"{_fmt(bs.cet1_capital)} - {_fmt(res.credit_loss)} - {_fmt(res.fire_sale_loss)} - "
            f"{_fmt(res.unrealised_charge_fv)} - {_fmt(res.unrealised_charge_htm)} = {_fmt(res.cet1_after)}",
            value=res.cet1_after, unit=C)
    tb.step("capital_ratio_before", "Capital ratio before stress", r"CET1 / RWA",
            f"{_fmt(bs.cet1_capital)} / {_fmt(bs.risk_weighted_assets)} = {res.capital_ratio_before:.6f}",
            value=res.capital_ratio_before, unit=F)
    tb.step("capital_ratio_after", "Capital ratio after stress", r"CET1' / RWA \quad (\text{RWA unchanged})",
            f"{_fmt(res.cet1_after)} / {_fmt(bs.risk_weighted_assets)} = {res.capital_ratio_after:.6f}",
            value=res.capital_ratio_after, unit=F)

    tb.step("hqla_before", "HQLA before stress", r"HQLA = \sum_j MV_j (1 - h_{level(j)})",
            f"= {_fmt(res.hqla_before)}", value=res.hqla_before, unit=C, table=res.lcr_rows_before or None)
    tb.step("outflows_before", "Stressed 30-day outflows before stress",
            r"O = \sum_s D_s(0.05\,\iota_s + 0.25(1-\iota_s)) + \sum_{w: m_w \le 30} W_w",
            f"= {_fmt(res.outflows_before)}", value=res.outflows_before, unit=C)
    tb.step("lcr_before", "LCR before stress", r"LCR = HQLA / O",
            f"{_fmt(res.hqla_before)} / {_fmt(res.outflows_before)} = {res.lcr_before:.6f}",
            value=res.lcr_before, unit=R)
    tb.step("hqla_after", "HQLA left after the run", r"HQLA' = \sum_j (1-f_j) MV^{post}_j (1 - h_j)",
            f"= {_fmt(res.hqla_after)}", value=res.hqla_after, unit=C, table=res.lcr_rows_after or None)
    tb.step("outflows_after", "Stressed outflows on the post-run balance sheet",
            r"O' = \sum_s D_s(1-r_s)(0.05\,\iota_s + 0.25(1-\iota_s)) + O_W^{\text{not repaid}}",
            f"= {_fmt(res.outflows_after)}", value=res.outflows_after, unit=C)
    tb.step("lcr_after", "LCR after stress", r"LCR' = HQLA' / O' \quad (0 \text{ if shortfall})",
            f"{_fmt(res.hqla_after)} / {_fmt(res.outflows_after)} = {res.lcr_after:.6f}",
            value=res.lcr_after, unit=R)
    tb.step("verdict", "Verdict",
            r"\text{pass} \iff CET1'/RWA \ge k_{cap} \ \wedge\ LCR' \ge k_{LCR}",
            f"capital {res.capital_ratio_after:.4f} {'<' if res.capital_breach else '>='} {sc.capital_threshold}; "
            f"LCR {res.lcr_after:.4f} {'<' if res.liquidity_breach else '>='} {sc.lcr_threshold}"
            f"{' (shortfall)' if res.liquidity_shortfall > 0 else ''} -> {res.verdict} "
            f"(binding: {res.binding_constraint})")
