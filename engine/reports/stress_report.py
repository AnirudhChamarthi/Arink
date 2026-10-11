"""Excel report for POST /risk/stress."""

from __future__ import annotations

from reports.excel_writer import validate_report_path, write_nlq_report
from schemas.contract import StressResult


def write_stress_report(result: StressResult) -> str:
    pct = result.portfolio_pct * 100.0
    topline = f"{pct:.2f}%"
    label = f"Stressed P&L ({result.scenario})"
    formula = [
        f"Scenario: {result.scenario}",
        f"Portfolio P&L = {result.portfolio_pnl:,.0f}",
        f"Portfolio impact = {topline}",
    ]
    worst = result.worst_positions[:5]
    formula += [f"  {w.ticker}: {w.pct_impact * 100:.2f}% of portfolio" for w in worst]
    detail = [
        {
            "ticker": p.ticker,
            "pnl_impact": p.pnl_impact,
            "pct_impact": p.pct_impact * 100.0,
        }
        for p in sorted(result.positions, key=lambda x: x.pnl_impact)
    ]
    explanation = (
        f"Portfolio P&L under {result.scenario}: {result.portfolio_pnl:,.0f} "
        f"({topline} of MV). Worst: {', '.join(w.ticker for w in worst) or 'n/a'}."
    )
    query = f"Stress: {result.scenario}"
    path = write_nlq_report(
        slug=f"stress_{result.scenario}",
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=explanation,
        models_used=[f"stress:{result.scenario}"],
        detail_rows=detail,
        query=query,
        model_parameters={"scenario": result.scenario},
    )
    return validate_report_path(path)


def stress_result_with_report(result: StressResult) -> StressResult:
    report_path = write_stress_report(result)
    return result.model_copy(update={"excel_report_path": report_path})
