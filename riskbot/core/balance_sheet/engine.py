"""Core Q2 stress engine: rate shock, credit loss, deposit run, liquidation waterfall, capital and LCR.

``evaluate(bs, scenario)`` is a pure function returning every intermediate quantity in a
``StressResult``; ``q2.resilience`` turns it into a trace and ``q2.reverse_stress`` bisects on it.
See README.md for the formulas and every simplifying assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from riskbot.contract.types import BankBalanceSheet, BsAsset

from . import instruments as ins

SECURITY_KINDS = ("hqla_securities", "afs_securities", "htm_securities")
FAIR_VALUE_KINDS = ("hqla_securities", "afs_securities")  # carried at fair value (marks through capital)
NMD_DURATION_YEARS = 2.0  # effective duration of a non-maturity deposit with beta 0 (illustrative)
LCR_HAIRCUTS = {"1": 0.0, "2a": 0.15, "2b": 0.50}
LCR_RUNOFF_INSURED = 0.05
LCR_RUNOFF_UNINSURED = 0.25
WHOLESALE_WINDOW_DAYS = 30
LCR_CAP = 100.0  # reported LCR is capped so that it stays finite when stressed outflows vanish
VASICEK_Q = {"base": 0.90, "adverse": 0.99}

RunSpeed = Literal["none", "slow", "fast", "uniform"]


@dataclass(frozen=True)
class Scenario:
    """One stress scenario. ``run_speed='uniform'`` applies ``uniform_outflow`` to every deposit segment."""

    rate_shock_bp: float = 200.0
    run_speed: RunSpeed = "slow"
    loss_severity: str = "base"
    htm_treatment: str = "at_cost"
    capital_threshold: float = 0.07
    lcr_threshold: float = 1.0
    fire_sale_impact: float = 0.05
    uniform_outflow: float = 0.0

    @property
    def dy(self) -> float:
        return self.rate_shock_bp / 10_000.0


@dataclass
class AssetRow:
    id: str
    kind: str
    book: float
    mv: float
    carrying: float  # value at which capital currently carries the asset
    t_dur: float
    y: float
    dmod: float
    conv: float
    source: str
    dv: float
    mv_post: float
    hqla_level: str | None
    sold_share: float = 0.0
    nii: float = 0.0


@dataclass
class StressResult:
    scenario: Scenario
    assets: list[AssetRow]
    liabilities: list[dict]
    swaps: list[dict]
    delta_assets: float
    delta_liabilities: float
    delta_swaps: float
    delta_eve: float
    delta_eve_pct_cet1: float
    nii_rows: list[dict]
    nii_assets: float
    nii_liabilities: float
    nii_swaps: float
    delta_nii_12m: float
    credit_rows: list[dict]
    credit_loss: float
    securities_rows: list[dict]
    unrealised_securities_loss: float
    outflow_rows: list[dict]
    deposit_outflow: float
    wholesale_outflow: float
    total_need: float
    cash_available: float
    cash_used: float
    hqla_sec_pool: float
    hqla_sec_sold: float
    hqla_sale_loss: float
    saleable_pool: float
    fire_sale: ins.FireSale
    fire_sale_mv_sold: float
    fire_sale_carrying_sold: float
    fire_sale_realised: float
    liquidity_shortfall: float
    fire_sale_loss: float
    unrealised_charge_fv: float
    unrealised_charge_htm: float
    cet1_after: float
    capital_ratio_before: float
    capital_ratio_after: float
    lcr_rows_before: list[dict]
    hqla_before: float
    outflows_before: float
    lcr_before: float
    lcr_rows_after: list[dict]
    hqla_after: float
    outflows_after: float
    lcr_after: float
    capital_breach: bool
    liquidity_breach: bool
    verdict: str
    binding_constraint: str
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------
# Building blocks
# ------------------------------------------------------------------------------------------------


def duration_maturity(a: BsAsset) -> float:
    """Maturity used for rate risk: time to the next repricing, capped at final maturity; 0 for cash."""
    if a.kind == "cash":
        return 0.0
    return min(a.maturity_years, a.repricing_years)


def asset_yield(a: BsAsset, policy_rate: float) -> float:
    """Par assumption: yield = coupon; a zero (or negative) coupon instrument is discounted at the policy rate."""
    return a.coupon_rate if a.coupon_rate > 0 else policy_rate


def asset_risk(a: BsAsset, policy_rate: float) -> tuple[float, float, float, float, str]:
    """(duration maturity T, yield y, modified duration, convexity, source) for one asset."""
    t = duration_maturity(a)
    y = asset_yield(a, policy_rate)
    if a.kind == "cash":
        return 0.0, y, 0.0, 0.0, "cash"
    if a.modified_duration is not None:
        d = a.modified_duration
        if a.convexity is not None:
            return t, y, d, a.convexity, "given"
        return t, y, d, ins.zero_coupon_convexity_for_duration(d, y), "given D, zero-coupon C"
    _, d, c = ins.bond_risk(t, a.coupon_rate, y)
    if a.convexity is not None:
        return t, y, d, a.convexity, "derived D, given C"
    return t, y, d, c, "derived"


def hqla_level(a: BsAsset) -> str | None:
    """LCR level: cash is always level 1; HQLA securities without a level are treated as level 1."""
    if a.kind == "cash":
        return "1"
    if a.kind == "hqla_securities":
        return a.hqla_level or "1"
    return a.hqla_level


def lcr_deposit_weight(insured_share: float) -> float:
    return insured_share * LCR_RUNOFF_INSURED + (1.0 - insured_share) * LCR_RUNOFF_UNINSURED


def deposit_duration(rate_beta: float) -> float:
    return NMD_DURATION_YEARS * (1.0 - rate_beta)


def swap_duration(fixed_rate: float, maturity: float, policy_rate: float) -> float:
    y = fixed_rate if fixed_rate > 0 else policy_rate
    return ins.bond_risk(maturity, fixed_rate, y)[1]


def safe_lcr(hqla: float, outflows: float, shortfall: float = 0.0) -> float:
    if shortfall > 0:
        return 0.0
    if outflows <= 1e-12 * max(1.0, hqla):
        return LCR_CAP if hqla > 0 else 0.0
    return min(LCR_CAP, hqla / outflows)


# ------------------------------------------------------------------------------------------------
# Evaluation
# ------------------------------------------------------------------------------------------------


def evaluate(bs: BankBalanceSheet, sc: Scenario) -> StressResult:  # noqa: C901 - one linear calculation
    dy = sc.dy
    warnings: list[str] = []

    # --- 1. Asset revaluation ---------------------------------------------------------------
    rows: list[AssetRow] = []
    for a in bs.assets:
        t, y, d, c, src = asset_risk(a, bs.policy_rate)
        dv = ins.value_change(a.market_value, d, c, dy)
        carrying = a.book_value if a.kind == "htm_securities" else (
            a.market_value if a.kind in FAIR_VALUE_KINDS else a.book_value)
        rows.append(AssetRow(a.id, a.kind, a.book_value, a.market_value, carrying, t, y, d, c, src, dv,
                             a.market_value + dv, hqla_level(a)))
        if c > 0 and dy > d / c:
            warnings.append(f"asset {a.id}: shock beyond the convexity vertex D/C = {1e4 * d / c:.0f} bp; the "
                            "second-order approximation then understates the loss")
    delta_assets = sum(r.dv for r in rows)

    # --- 2. Liabilities and hedges ------------------------------------------------------------
    liabs = []
    for dseg in bs.deposits:
        dur = deposit_duration(dseg.rate_beta)
        liabs.append({"item": dseg.segment, "type": "deposit", "amount": dseg.balance, "duration": dur,
                      "delta_value": -dseg.balance * dur * dy})
    for w in bs.wholesale_funding:
        dur = w.maturity_days / 365.0
        liabs.append({"item": w.id, "type": "wholesale", "amount": w.amount, "duration": dur,
                      "delta_value": -w.amount * dur * dy})
    delta_liabs = sum(r["delta_value"] for r in liabs)
    swaps = []
    for h in bs.hedges:
        dsw = swap_duration(h.fixed_rate, h.maturity_years, bs.policy_rate)
        sign = 1.0 if h.pay_fixed else -1.0
        swaps.append({"id": h.id, "notional": h.notional, "pay_fixed": h.pay_fixed, "duration": dsw,
                      "delta_value": sign * h.notional * dsw * dy})
    delta_swaps = sum(r["delta_value"] for r in swaps)
    delta_eve = delta_assets - delta_liabs + delta_swaps

    # --- 3. NII (12 months, static balance sheet) ---------------------------------------------
    nii_rows = []
    for r, a in zip(rows, bs.assets):
        reprice = 0.0 if a.kind == "cash" else a.repricing_years
        if reprice < 1.0:
            r.nii = a.book_value * dy * (1.0 - reprice)
            nii_rows.append({"item": a.id, "side": "asset", "amount": a.book_value, "reprice_years": reprice,
                             "beta": 1.0, "delta_nii": r.nii})
    nii_assets = sum(x["delta_nii"] for x in nii_rows)
    for dseg in bs.deposits:
        v = -dseg.balance * dseg.rate_beta * dy
        nii_rows.append({"item": dseg.segment, "side": "deposit", "amount": dseg.balance, "reprice_years": 0.0,
                         "beta": dseg.rate_beta, "delta_nii": v})
    for w in bs.wholesale_funding:
        if w.maturity_days < 365:
            tr = w.maturity_days / 365.0
            nii_rows.append({"item": w.id, "side": "wholesale", "amount": w.amount, "reprice_years": tr,
                             "beta": 1.0, "delta_nii": -w.amount * dy * (1.0 - tr)})
    nii_liabs = -sum(x["delta_nii"] for x in nii_rows if x["side"] in ("deposit", "wholesale"))
    nii_swaps = 0.0
    for h in bs.hedges:
        v = (1.0 if h.pay_fixed else -1.0) * h.notional * dy
        nii_swaps += v
        nii_rows.append({"item": h.id, "side": "swap", "amount": h.notional, "reprice_years": 0.0,
                         "beta": 1.0, "delta_nii": v})
    delta_nii = nii_assets - nii_liabs + nii_swaps

    # --- 4. Credit loss --------------------------------------------------------------------------
    q = VASICEK_Q[sc.loss_severity]
    credit_rows = []
    for p in bs.loan_pools:
        pds = ins.vasicek_pd(p.pd, p.asset_correlation, q)
        credit_rows.append({"segment": p.segment, "ead": p.ead, "pd": p.pd, "rho": p.asset_correlation,
                            "lgd": p.lgd, "pd_stressed": pds, "loss": p.ead * p.lgd * pds})
    credit_loss = sum(r["loss"] for r in credit_rows)

    # --- 5. Securities marks -----------------------------------------------------------------
    sec = [r for r in rows if r.kind in SECURITY_KINDS]
    unrealised = -sum(r.dv for r in sec)

    # --- 6. Run ---------------------------------------------------------------------------------
    outflow_rows = []
    for dseg in bs.deposits:
        rate = {"none": 0.0, "slow": dseg.runoff_slow, "fast": dseg.runoff_fast,
                "uniform": sc.uniform_outflow}[sc.run_speed]
        outflow_rows.append({"segment": dseg.segment, "balance": dseg.balance, "runoff": rate,
                             "outflow": dseg.balance * rate, "remaining": dseg.balance * (1.0 - rate),
                             "lcr_weight": lcr_deposit_weight(dseg.insured_share)})
    deposit_outflow = sum(r["outflow"] for r in outflow_rows)
    wholesale_repaid = sc.run_speed != "none"
    short_wholesale = [w for w in bs.wholesale_funding if w.maturity_days <= WHOLESALE_WINDOW_DAYS]
    wholesale_outflow = sum(w.amount for w in short_wholesale) if wholesale_repaid else 0.0
    need = deposit_outflow + wholesale_outflow

    # --- 7. Liquidation waterfall: cash -> HQLA securities -> AFS -> HTM ---------------------
    cash_rows = [r for r in rows if r.kind == "cash"]
    cash_avail = sum(r.mv for r in cash_rows)
    cash_used = min(need, cash_avail)
    for r in cash_rows:
        r.sold_share = cash_used / cash_avail if cash_avail > 0 else 0.0
    rem = need - cash_used

    hq = [r for r in rows if r.kind == "hqla_securities"]
    hq_pool = sum(r.mv_post for r in hq)
    hq_sold = min(rem, hq_pool)
    hq_share = hq_sold / hq_pool if hq_pool > 0 else 0.0
    for r in hq:
        r.sold_share = hq_share
    hq_loss = sum(hq_share * r.carrying for r in hq) - hq_sold
    rem -= hq_sold

    afs = [r for r in rows if r.kind == "afs_securities"]
    htm = [r for r in rows if r.kind == "htm_securities"]
    s_afs = sum(r.mv_post for r in afs)
    s_htm = sum(r.mv_post for r in htm)
    pool = s_afs + s_htm
    fs = ins.solve_fire_sale(rem, pool, sc.fire_sale_impact)
    if not fs.converged:  # pragma: no cover - solve_fire_sale always finishes by bisection
        warnings.append("fire-sale fixed point did not converge")
    mv_sold = fs.share * pool
    m_afs = min(mv_sold, s_afs)
    m_htm = mv_sold - m_afs
    f_afs = m_afs / s_afs if s_afs > 0 else 0.0
    f_htm = min(1.0, m_htm / s_htm) if s_htm > 0 else 0.0
    for r in afs:
        r.sold_share = f_afs
    for r in htm:
        r.sold_share = f_htm
    carrying_sold = sum(f_afs * r.carrying for r in afs) + sum(f_htm * r.carrying for r in htm)
    fs_realised = carrying_sold - fs.proceeds if mv_sold > 0 else 0.0
    shortfall = fs.shortfall
    if shortfall > 0:
        warnings.append(f"liquidity shortfall of {shortfall:,.0f}: outflows exceed all saleable assets")
    fire_sale_loss = hq_loss + fs_realised

    securities_rows = []
    for r in sec:
        securities_rows.append({"id": r.id, "kind": r.kind, "book": r.book, "carrying": r.carrying,
                                "mv_before": r.mv, "delta_value": r.dv, "mv_after": r.mv_post,
                                "unrealised_loss": -r.dv, "sold_share": r.sold_share,
                                "embedded_loss_vs_book": r.book - r.mv_post})

    # --- 8. Capital -------------------------------------------------------------------------------
    unreal_fv = sum((1.0 - r.sold_share) * (r.carrying - r.mv_post) for r in rows if r.kind in FAIR_VALUE_KINDS)
    unreal_htm = (sum((1.0 - r.sold_share) * (r.book - r.mv_post) for r in htm)
                  if sc.htm_treatment == "mark_to_market" else 0.0)
    cet1_after = bs.cet1_capital - credit_loss - fire_sale_loss - unreal_fv - unreal_htm
    cr_before = bs.cet1_capital / bs.risk_weighted_assets
    cr_after = cet1_after / bs.risk_weighted_assets

    # --- 9. LCR -----------------------------------------------------------------------------------
    lcr_rows_before, lcr_rows_after = [], []
    hqla_before = hqla_after = 0.0
    for r in rows:
        if r.hqla_level is None:
            continue
        h = LCR_HAIRCUTS[r.hqla_level]
        vb = r.mv * (1.0 - h)
        va = (1.0 - r.sold_share) * r.mv_post * (1.0 - h)
        hqla_before += vb
        hqla_after += va
        lcr_rows_before.append({"id": r.id, "level": r.hqla_level, "haircut": h, "value": r.mv, "hqla": vb})
        lcr_rows_after.append({"id": r.id, "level": r.hqla_level, "haircut": h,
                               "value": (1.0 - r.sold_share) * r.mv_post, "hqla": va})
    short_amt = sum(w.amount for w in short_wholesale)
    outflows_before = sum(r["balance"] * r["lcr_weight"] for r in outflow_rows) + short_amt
    outflows_after = sum(r["remaining"] * r["lcr_weight"] for r in outflow_rows) + (
        0.0 if wholesale_repaid else short_amt)
    for w in short_wholesale:
        lcr_rows_before.append({"id": w.id, "level": "outflow", "haircut": 1.0, "value": w.amount, "hqla": 0.0})
    lcr_before = safe_lcr(hqla_before, outflows_before)
    lcr_after = safe_lcr(hqla_after, outflows_after, shortfall)

    cap_breach = cr_after < sc.capital_threshold
    liq_breach = lcr_after < sc.lcr_threshold or shortfall > 0
    verdict = "fail" if cap_breach or liq_breach else "pass"
    binding = {(False, False): "none", (True, False): "capital", (False, True): "liquidity",
               (True, True): "both"}[(cap_breach, liq_breach)]

    return StressResult(
        scenario=sc, assets=rows, liabilities=liabs, swaps=swaps, delta_assets=delta_assets,
        delta_liabilities=delta_liabs, delta_swaps=delta_swaps, delta_eve=delta_eve,
        delta_eve_pct_cet1=delta_eve / bs.cet1_capital, nii_rows=nii_rows, nii_assets=nii_assets,
        nii_liabilities=nii_liabs, nii_swaps=nii_swaps, delta_nii_12m=delta_nii, credit_rows=credit_rows,
        credit_loss=credit_loss, securities_rows=securities_rows, unrealised_securities_loss=unrealised,
        outflow_rows=outflow_rows, deposit_outflow=deposit_outflow, wholesale_outflow=wholesale_outflow,
        total_need=need, cash_available=cash_avail, cash_used=cash_used, hqla_sec_pool=hq_pool,
        hqla_sec_sold=hq_sold, hqla_sale_loss=hq_loss, saleable_pool=pool, fire_sale=fs,
        fire_sale_mv_sold=mv_sold, fire_sale_carrying_sold=carrying_sold, fire_sale_realised=fs_realised,
        liquidity_shortfall=shortfall, fire_sale_loss=fire_sale_loss, unrealised_charge_fv=unreal_fv,
        unrealised_charge_htm=unreal_htm, cet1_after=cet1_after, capital_ratio_before=cr_before,
        capital_ratio_after=cr_after, lcr_rows_before=lcr_rows_before, hqla_before=hqla_before,
        outflows_before=outflows_before, lcr_before=lcr_before, lcr_rows_after=lcr_rows_after,
        hqla_after=hqla_after, outflows_after=outflows_after, lcr_after=lcr_after, capital_breach=cap_breach,
        liquidity_breach=liq_breach, verdict=verdict, binding_constraint=binding, warnings=warnings,
    )


def constraint_value(res: StressResult, target: str) -> float:
    """The quantity a reverse stress test drives below its threshold."""
    return res.capital_ratio_after if target == "capital" else res.lcr_after


def is_breach(res: StressResult, target: str) -> bool:
    return res.capital_breach if target == "capital" else res.liquidity_breach
