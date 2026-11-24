"""Realistic hand-built scenarios (low-risk and high-risk) for each question."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from riskbot.contract.fakes import fake_dataset
from riskbot.contract.types import (
    ClimateHolding,
    ClimatePortfolio,
    Comparison,
    ConclusionFlip,
    MarketDataset,
    MarketPosition,
    QuestionId,
    SensitivityRow,
    SwapHedge,
    VariationResult,
    WholesaleFunding,
)

from ._builders import compare, failed, finding, result

Q1, Q2, Q3 = QuestionId.Q1, QuestionId.Q2, QuestionId.Q3
METHODS = ["normal", "student_t", "historical", "fhs", "evt", "montecarlo"]


@dataclass
class Scenario:
    question: QuestionId
    dataset: Any
    results: list[VariationResult]
    comparison: Comparison


# ----------------------------------------------------------------------------------------------
# Q1
# ----------------------------------------------------------------------------------------------


def diversified_market() -> MarketDataset:
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    tickers = [f"T{chr(65 + i)}" for i in range(11)]  # TA..TK, no digits
    positions = [MarketPosition(ticker=t, quantity=100, price=10.0) for t in tickers]
    positions.append(MarketPosition(ticker="CASH", asset_class="cash", quantity=100, price=1.0))
    rets = {t: [0.001 * ((i * (k + 3)) % 7 - 3) for i in range(30)] for k, t in enumerate(tickers)}
    return MarketDataset(name="diversified long-only", as_of=dates[-1], synthetic=True, positions=positions,
                         dates=dates, returns=rets)


def q1_results(var: dict[str, float], verdicts: dict[str, str] | None = None, zone: str = "green",
               history_days: int = 1500, quality: str = "good", findings=None, exceptions: dict[str, int] | None = None,
               window_ratio: float = 1.05, dq_ok: bool = True) -> list[VariationResult]:
    out = []
    for m, v in var.items():
        for w in (250, 750):
            value = v if w == 250 else v * window_ratio
            metrics = {"var": value, "es": value * 1.25, "var_amount": value * 1e7, "es_amount": value * 1.25e7,
                       "gross_exposure": 1e7, "backtest_days": 500.0,
                       "backtest_exceptions": float((exceptions or {}).get(m, 4)),
                       "backtest_exception_rate": (exceptions or {}).get(m, 4) / 500, "kupiec_p": 0.4,
                       "independence_p": 0.5}
            verdict = (verdicts or {}).get(m, "pass")
            out.append(result("q1.var", metrics, {"basel_zone": zone if verdict == "fail" else "green",
                                                  "backtest_verdict": verdict},
                              {"method": m, "window_days": w, "confidence": 0.99, "horizon_days": 5}))
    if dq_ok:
        out.append(result("q1.data_quality", {"n_positions": 12.0, "history_days": float(history_days),
                                              "missing_share": 0.004, "stale_series": 1.0, "outlier_count": 3.0},
                          {"quality": quality}, {"stale_days": 5}, role="extra", findings=findings or []))
    else:
        out.append(failed("q1.data_quality", {"stale_days": 5}, role="extra"))
    return out


def q1_low() -> Scenario:
    res = q1_results({"normal": 0.030, "student_t": 0.031, "historical": 0.032, "fhs": 0.031, "evt": 0.033,
                      "montecarlo": 0.030})
    return Scenario(Q1, diversified_market(), res, compare(Q1, res))


def q1_high() -> Scenario:
    var = {"normal": 0.020, "student_t": 0.031, "historical": 0.036, "fhs": 0.041, "evt": 0.052, "montecarlo": 0.021}
    verdicts = {"normal": "fail", "montecarlo": "fail", "student_t": "fail", "historical": "fail", "fhs": "pass",
                "evt": "pass"}
    res = q1_results(var, verdicts, zone="red", history_days=300, quality="poor",
                     findings=[finding("missing_returns", "error", subject="AAA"), finding("stale_price", "warning")],
                     exceptions={"normal": 14, "montecarlo": 13}, window_ratio=1.4)
    sens = [SensitivityRow(dimension="window_days", metric="var", medians={"250": 0.031, "750": 0.043},
                           effect=0.012)]
    return Scenario(Q1, fake_dataset(Q1), res, compare(Q1, res, sensitivity=sens))


def q1_missing() -> Scenario:
    res = [failed("q1.var", {"method": m, "window_days": 250}) for m in METHODS]
    res.append(failed("q1.data_quality", {"stale_days": 5}, role="extra"))
    return Scenario(Q1, fake_dataset(Q1), res, Comparison(question=Q1, metric_ranges={}))


# ----------------------------------------------------------------------------------------------
# Q2
# ----------------------------------------------------------------------------------------------


def q2_resilience(shock: int, run: str, htm: str, verdict: str, binding: str, eve_pct: float) -> VariationResult:
    metrics = {"delta_eve": eve_pct * 60, "delta_eve_pct_cet1": eve_pct, "delta_nii_12m": -1.5, "credit_loss": 8.0,
               "unrealised_securities_loss": 12.0, "deposit_outflow": 90.0, "fire_sale_loss": 2.0,
               "cet1_after": 45.0, "capital_ratio_before": 0.0857, "capital_ratio_after": 0.064,
               "lcr_before": 1.4, "lcr_after": 0.9}
    return result("q2.resilience", metrics, {"verdict": verdict, "binding_constraint": binding},
                  {"rate_shock_bp": shock, "run_speed": run, "loss_severity": "base", "htm_treatment": htm})


def q2_dq(**kw: float) -> VariationResult:
    metrics = {"loan_reconciliation_gap": 0.0, "uninsured_deposit_share": 0.4, "largest_segment_share": 0.3,
               "hqla_share": 0.12, "duration_gap_years": 2.5, "hedge_ratio": 0.25, "htm_share_of_securities": 0.3}
    metrics.update(kw)
    return result("q2.data_quality", metrics, {"quality": "good"}, {}, role="extra")


def q2_low() -> Scenario:
    ds = fake_dataset(Q2).model_copy(update={
        "governance": {"cro_vacancy_months": 0, "board_risk_expertise": True, "risk_committee_meetings_per_year": 8,
                       "hedges_reduced_last_year": False}})
    res = [q2_resilience(s, r, h, "pass", "none", -0.02 if s > 0 else 0.01)
           for s in (-200, 200) for r in ("slow", "fast") for h in ("at_cost", "mark_to_market")]
    res.append(q2_dq(uninsured_deposit_share=0.12, largest_segment_share=0.10, hqla_share=0.25,
                     duration_gap_years=0.6, hedge_ratio=0.7, htm_share_of_securities=0.05))
    res.append(result("q2.reverse_stress", {"breakeven_deposit_outflow": 0.45}, {"outflow_found": "yes",
                                                                                "rate_found": "no"},
                      {"target": "liquidity"}, role="extra"))
    return Scenario(Q2, ds, res, compare(Q2, res))


def q2_high() -> Scenario:
    base = fake_dataset(Q2)
    ds = base.model_copy(update={
        "wholesale_funding": [WholesaleFunding(id="repo", amount=300, maturity_days=7, rate=0.05)],
        "hedges": [SwapHedge(id="swap", notional=10, fixed_rate=0.03, maturity_years=2)],
        "governance": {"cro_vacancy_months": 8, "hedges_reduced_last_year": True, "board_risk_expertise": False},
    })
    res = []
    for s in (-200, 100, 300):
        for r in ("slow", "fast"):
            for h in ("at_cost", "mark_to_market"):
                fail = (s == 300 and r == "fast") or (s == 300 and h == "mark_to_market")
                res.append(q2_resilience(s, r, h, "fail" if fail else "pass",
                                         ("both" if r == "fast" else "capital") if fail else "none",
                                         -0.35 if s == 300 else (-0.1 if s > 0 else 0.05)))
    res.append(q2_dq(uninsured_deposit_share=0.82, largest_segment_share=0.65, hqla_share=0.05,
                     duration_gap_years=5.5, hedge_ratio=0.03, htm_share_of_securities=0.62,
                     loan_reconciliation_gap=0.08))
    res.append(result("q2.reverse_stress", {"breakeven_deposit_outflow": 0.08}, {"outflow_found": "yes",
                                                                                "rate_found": "no"},
                      {"target": "liquidity"}, role="extra"))
    flips = [ConclusionFlip(label="verdict", dimension="htm_treatment", from_value="at_cost",
                            to_value="mark_to_market", outcome_from="pass", outcome_to="fail",
                            description="Marking HTM to market turns pass into fail at +300 bp, slow run.")]
    return Scenario(Q2, ds, res, compare(Q2, res, flips=flips))


def q2_missing() -> Scenario:
    res = [failed("q2.resilience", {"rate_shock_bp": 200}), failed("q2.data_quality", {}, role="extra")]
    return Scenario(Q2, fake_dataset(Q2), res, Comparison(question=Q2, metric_ranges={}))


# ----------------------------------------------------------------------------------------------
# Q3
# ----------------------------------------------------------------------------------------------


def clean_climate() -> ClimatePortfolio:
    hs = [ClimateHolding(issuer=f"Tech{c}", sector=s, market_value=1000, evic=50000, revenue=10000, scope1=100,
                         scope2=50, scope3=500, data_quality=1, emissions_year=2025)
          for c, s in zip("ABCDEFGH", ["technology", "health", "financials", "consumer", "technology",
                                        "industrials", "health", "telecom"])]
    hs.append(ClimateHolding(issuer="Gridco", sector="utilities", market_value=500, evic=50000, revenue=8000,
                             scope1=9000, scope2=100, scope3=2000, data_quality=2, emissions_year=2025))
    return ClimatePortfolio(name="clean book", as_of=dt.date(2026, 11, 1), synthetic=True, holdings=hs)


def q3_transition(loss: float, scen: str, path: str, md: str, est: float) -> VariationResult:
    metrics = {"loss_pct": loss, "loss_p05": loss * 0.6, "loss_p95": loss * 1.5, "loss_amount": loss * 3000,
               "waci": 180.0, "financed_emissions": 2400.0, "carbon_price_end": 140.0, "alignment_ratio": 1.6,
               "estimated_share": est}
    return result("q3.transition", metrics, {"exposure_level": "moderate"},
                  {"scenario": scen, "price_path": path, "missing_data": md, "include_scope3": False,
                   "horizon_years": 10, "n_sims": 2000})


def q3_dq(**kw: float) -> VariationResult:
    metrics = {"coverage_scope12": 0.7, "coverage_scope3": 0.2, "mean_data_quality": 3.0, "stale_share": 0.05,
               "controversy_share": 0.1}
    quality = kw.pop("quality", "fair")
    metrics.update(kw)
    return result("q3.data_quality", metrics, {"quality": quality}, {"stale_years": 2}, role="extra",
                  findings=[finding("stale_emissions", "warning", field="holdings.emissions_year", subject="Oilco")])


def q3_low() -> Scenario:
    res = [q3_transition(l, s, "central", "sector_average", 0.04)
           for l, s in ((0.010, "orderly"), (0.012, "disorderly"), (0.011, "hot_house"))]
    res.append(q3_dq(coverage_scope12=0.96, coverage_scope3=0.85, mean_data_quality=1.4, stale_share=0.0,
                     controversy_share=0.0, quality="good"))
    return Scenario(Q3, clean_climate(), res, compare(Q3, res))


def q3_high() -> Scenario:
    base = fake_dataset(Q3)
    hs = list(base.holdings) + [
        ClimateHolding(issuer="Coalco", sector="materials", market_value=800, evic=9000, revenue=3000,
                       exclusion_flags=["thermal_coal"], controversy_flags=["spill"]),
        ClimateHolding(issuer="Shortco", sector="energy", market_value=-300, evic=9000, revenue=3000,
                       exclusion_flags=["arctic_drilling"]),
    ]
    ds = base.model_copy(update={"holdings": hs})
    res = [q3_transition(l, s, p, md, e) for l, s, p, md, e in (
        (0.008, "orderly", "low", "exclude", 0.0), (0.04, "disorderly", "central", "sector_average", 0.55),
        (0.12, "disorderly", "high", "conservative", 0.68))]
    res.append(q3_dq(coverage_scope12=0.32, coverage_scope3=0.05, mean_data_quality=4.2, stale_share=0.55,
                     controversy_share=0.35, quality="poor"))
    return Scenario(Q3, ds, res, compare(Q3, res))


def q3_missing() -> Scenario:
    res = [failed("q3.transition", {"scenario": "orderly"}), failed("q3.data_quality", {}, role="extra")]
    return Scenario(Q3, fake_dataset(Q3), res, Comparison(question=Q3, metric_ranges={}))


ALL = {
    "q1_low": q1_low, "q1_high": q1_high, "q1_missing": q1_missing,
    "q2_low": q2_low, "q2_high": q2_high, "q2_missing": q2_missing,
    "q3_low": q3_low, "q3_high": q3_high, "q3_missing": q3_missing,
}
