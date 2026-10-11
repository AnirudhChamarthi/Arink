"""Master full-risk Excel workbook (all core models)."""

from __future__ import annotations

from models.greeks import run_greeks
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import run_var
from reports.excel_writer import write_full_report
from reports.report_charts import build_full_report_charts
from schemas.contract import (
    EnrichedPortfolio,
    StressScenario,
    VarMethod,
)


def generate_full_report(
    portfolio: EnrichedPortfolio,
    *,
    method: VarMethod = VarMethod.PARAMETRIC,
    confidence: float = 0.99,
    horizon_days: int = 1,
    stress_scenario: StressScenario = StressScenario.CREDIT_2008,
    exclusion_filters: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (excel_path, summary_text for UI)."""
    filters = exclusion_filters or []
    var_r = run_var(portfolio, method, confidence, horizon_days)
    greeks = run_greeks(portfolio)
    esg = run_sustainability(
        portfolio,
        filters,
        include_carbon_var=True,
        run_exclusion_check=True,
    )
    stress = run_stress(portfolio, stress_scenario, None)

    charts = build_full_report_charts(
        portfolio=portfolio,
        var_result=var_r,
        greeks_result=greeks,
        sustainability_result=esg,
        stress_result=stress,
    )

    summary = (
        f"Full risk snapshot — {portfolio.portfolio_name}\n\n"
        f"VaR ({var_r.method.value}, {confidence:.0%}, {horizon_days}d): {var_r.var * 100:.2f}%\n"
        f"CVaR: {var_r.cvar * 100:.2f}%\n"
        f"Portfolio Δ: {greeks.portfolio_delta:,.0f}\n"
        f"ESG score: {esg.portfolio_esg_score:.1f}\n"
        f"Carbon intensity: {esg.carbon_intensity_weighted:.1f} tCO2e/$M\n"
        f"Carbon VaR: {esg.carbon_var * 100:.2f}%\n"
        f"{stress.scenario} stress P&L: {stress.portfolio_pct * 100:.2f}% of MV\n"
    )
    if esg.exclusion_breaches:
        summary += (
            "Exclusion breaches: "
            + ", ".join(f"{b.ticker} ({b.filter})" for b in esg.exclusion_breaches[:5])
            + "\n"
        )
    else:
        summary += "No exclusion breaches.\n"

    path = write_full_report(
        portfolio=portfolio,
        var_result=var_r,
        greeks_result=greeks,
        sustainability_result=esg,
        stress_result=stress,
        chart_images=charts,
        model_parameters={
            "var_method": method.value,
            "confidence": confidence,
            "horizon_days": horizon_days,
            "stress_scenario": stress.scenario,
            "exclusion_filters": ", ".join(filters) if filters else "none",
        },
    )
    return path, summary
