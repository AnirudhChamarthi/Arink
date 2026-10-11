"""Run routed models and assemble NLQ results."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from models.garch import run_garch
from models.greeks import run_greeks
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import run_var
from nlp.anthropic_config import anthropic_model
from nlp.claude_router import RoutingInstruction, route_query
from reports.excel_writer import write_nlq_report
from reports.report_charts import build_nlq_charts
from schemas.contract import (
    EnrichedPortfolio,
    NlqResult,
    RiskLimits,
    StressScenario,
    VarMethod,
)

logger = logging.getLogger(__name__)


@dataclass
class _ModelOutput:
    topline_number: str
    topline_label: str
    formula_breakdown: list[str]
    explanation: str
    models_used: list[str]
    detail_rows: list[dict[str, Any]]


def run_nlq(
    query: str,
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
) -> NlqResult:
    summary = _portfolio_summary(portfolio)
    routing = route_query(query, summary)
    output = _execute_routing(routing, portfolio, limits)
    explanation = _finalize_explanation(
        query, routing.explanation_request, output.explanation, summary, output
    )
    slug = _query_slug(query)
    charts = build_nlq_charts(
        models_used=output.models_used,
        detail_rows=output.detail_rows,
        portfolio=portfolio,
    )
    report_path = write_nlq_report(
        slug=slug,
        topline_number=output.topline_number,
        topline_label=output.topline_label,
        formula_breakdown=output.formula_breakdown,
        explanation=explanation,
        models_used=output.models_used,
        detail_rows=output.detail_rows,
        query=query,
        chart_images=charts,
        model_parameters=_routing_parameters(routing, output),
    )
    return NlqResult(
        topline_number=output.topline_number,
        topline_label=output.topline_label,
        formula_breakdown=output.formula_breakdown,
        explanation=explanation,
        excel_report_path=report_path,
        models_used=output.models_used,
    )


def _portfolio_summary(portfolio: EnrichedPortfolio) -> str:
    tickers = [p.ticker for p in portfolio.positions]
    return (
        f"Name: {portfolio.portfolio_name}\n"
        f"Base currency: {portfolio.base_currency}\n"
        f"Benchmark: {portfolio.benchmark or 'none'}\n"
        f"Positions ({len(portfolio.positions)}): {', '.join(tickers[:20])}"
    )


def _execute_routing(
    routing: RoutingInstruction,
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
) -> _ModelOutput:
    primary = routing.models_to_run[0] if routing.models_to_run else "var"
    if primary == "concentration":
        return _run_concentration(portfolio, limits)
    if primary == "sustainability":
        return _run_sustainability(portfolio, limits, routing.parameters.get("sustainability", {}))
    if primary == "greeks":
        return _run_greeks(portfolio, limits, routing)
    if primary == "stress":
        return _run_stress(portfolio, limits, routing.parameters.get("stress", {}))
    if primary == "garch":
        return _run_garch(portfolio, limits, routing.parameters.get("garch", {}))
    return _run_var(portfolio, limits, routing)


def _position_weights(portfolio: EnrichedPortfolio) -> list[tuple[str, float, float]]:
    rows: list[tuple[str, float, float]] = []
    for pos in portfolio.positions:
        mv = pos.quantity if pos.asset_class.value == "Cash" else pos.current_price * pos.quantity
        rows.append((pos.ticker, max(mv, 0.0), pos.esg_score))
    total = sum(m for _, m, _ in rows) or 1.0
    return [(t, m / total, e) for t, m, e in rows]


def _run_var(
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
    routing: RoutingInstruction,
) -> _ModelOutput:
    params = routing.parameters.get("var") or {}
    confidence = float(params.get("confidence", 0.99))
    horizon = int(params.get("horizon_days", 1))
    method_str = str(params.get("method", "parametric"))
    try:
        method = VarMethod(method_str)
    except ValueError:
        method = VarMethod.PARAMETRIC

    result = run_var(portfolio, method, confidence, horizon)

    pct = result.var * 100.0
    topline = f"{pct:.2f}%"
    label = routing.topline_metric or f"{horizon}-Day {confidence:.0%} VaR ({result.method.value})"

    z = _z_value(confidence)
    formula = [
        "Parametric (variance-covariance) VaR:",
        "VaR = z × σ_portfolio × √h",
        f"z({confidence:.2%}) = {z:.4f}",
        f"σ_portfolio (daily) = {result.var / (z * np.sqrt(horizon)):.6f}",
        f"h = {horizon} day(s)",
        f"VaR = {result.var:.6f} → {topline}",
        f"CVaR (Expected Shortfall) = {result.cvar * 100:.2f}%",
    ]
    top_contrib = sorted(result.contributions, key=lambda c: c.pct_of_total, reverse=True)[:3]
    contrib_lines = [
        f"  {c.ticker}: {c.pct_of_total * 100:.1f}% of total VaR"
        for c in top_contrib
    ]
    limit_line = ""
    if limits.var_limit is not None:
        limit_line = (
            f"Portfolio VaR limit is {limits.var_limit * 100:.2f}%; "
            f"{'BREACH' if result.var > limits.var_limit else 'within limit'}."
        )
    explanation = (
        f"Portfolio {horizon}-day VaR at {confidence:.0%} confidence is {topline}. "
        f"Top contributors: {', '.join(c.ticker for c in top_contrib) or 'n/a'}. "
        f"{limit_line}"
    ).strip()
    detail = [
        {
            "ticker": c.ticker,
            "var_contribution": c.var_contribution,
            "pct_of_total": c.pct_of_total,
        }
        for c in result.contributions
    ]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula + ["Contributions:"] + contrib_lines,
        explanation=explanation,
        models_used=[f"var:{result.method.value}"],
        detail_rows=detail,
    )


def _run_concentration(portfolio: EnrichedPortfolio, limits: RiskLimits) -> _ModelOutput:
    weights = _position_weights(portfolio)
    ticker, weight, _ = max(weights, key=lambda x: x[1])
    pct = weight * 100.0
    topline = f"{pct:.2f}%"
    label = "Largest single-name weight"
    formula = [
        "Concentration = max(w_i) where w_i = MV_i / Σ MV",
        f"Largest position: {ticker}",
        f"Weight = {topline}",
    ]
    limit_msg = ""
    if limits.max_concentration is not None:
        breach = weight > limits.max_concentration
        limit_msg = (
            f" Max concentration limit is {limits.max_concentration * 100:.1f}% — "
            f"{'BREACH' if breach else 'within limit'}."
        )
    detail = [{"ticker": t, "weight_pct": w * 100.0} for t, w, _ in sorted(weights, key=lambda x: -x[1])]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=f"{ticker} is the largest holding at {topline} of portfolio market value.{limit_msg}",
        models_used=["concentration"],
        detail_rows=detail,
    )


def _run_sustainability(
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
    params: dict[str, Any],
) -> _ModelOutput:
    result = run_sustainability(
        portfolio,
        limits.exclusion_filters,
        include_carbon_var=bool(params.get("include_carbon_var", True)),
        carbon_price_shock=float(params.get("carbon_price_shock", 50.0)),
        run_exclusion_check=bool(params.get("run_exclusion_check", True)),
    )
    topline = f"{result.portfolio_esg_score:.1f}"
    label = "Portfolio weighted-average ESG score"
    formula = [
        "ESG_portfolio = Σ (w_i × ESG_i)",
        f"Carbon intensity (weighted) = {result.carbon_intensity_weighted:.1f} tCO2e/$M",
        f"Carbon VaR (shock) = {result.carbon_var * 100:.2f}% of portfolio MV",
        f"Paris alignment gap = {result.paris_alignment_gap_pct:.1f}%",
        f"Stranded asset exposure = {result.stranded_asset_exposure_pct * 100:.1f}%",
    ]
    breach_note = ""
    if result.exclusion_breaches:
        breach_note = (
            " Exclusions breached: "
            + ", ".join(f"{b.ticker} ({b.filter})" for b in result.exclusion_breaches[:5])
            + "."
        )
    esg_limit = ""
    if limits.esg_min_score is not None:
        esg_limit = (
            f" Minimum ESG limit is {limits.esg_min_score:.0f}; "
            f"{'below limit' if result.portfolio_esg_score < limits.esg_min_score else 'above limit'}."
        )
    detail = [
        {
            "ticker": row.ticker,
            "weight_pct": row.weight * 100.0,
            "esg_score": row.esg_score,
            "carbon_intensity": row.carbon_intensity,
        }
        for row in result.per_position_esg
    ]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=(
            f"Weighted-average ESG score is {topline} on a 0–100 scale.{esg_limit}{breach_note}"
        ),
        models_used=["sustainability"],
        detail_rows=detail,
    )


def _run_greeks(
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
    routing: RoutingInstruction,
) -> _ModelOutput:
    result = run_greeks(portfolio)
    topline = f"{result.portfolio_delta:,.0f}"
    label = routing.topline_metric or "Portfolio delta"
    formula = [
        "Portfolio Greeks = sum of position-level sensitivities",
        f"Δ = {result.portfolio_delta:,.2f}",
        f"Γ = {result.portfolio_gamma:,.4f}",
        f"Vega = {result.portfolio_vega:,.2f}",
        f"Θ = {result.portfolio_theta:,.2f}",
        f"ρ = {result.portfolio_rho:,.2f}",
    ]
    detail = [
        {
            "ticker": p.ticker,
            "delta": p.delta,
            "gamma": p.gamma,
            "vega": p.vega,
            "method": p.greeks_method.value,
        }
        for p in result.positions
    ]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=(
            f"Portfolio delta is {topline} (share-equivalent). "
            f"Largest |delta| positions drive directional risk."
        ),
        models_used=["greeks"],
        detail_rows=detail,
    )


def _run_stress(
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
    params: dict[str, Any],
) -> _ModelOutput:
    scenario_str = str(params.get("scenario", "2008_credit"))
    try:
        scenario = StressScenario(scenario_str)
    except ValueError:
        scenario = StressScenario.CREDIT_2008
    result = run_stress(portfolio, scenario, params.get("custom_shocks"))
    pct = result.portfolio_pct * 100.0
    topline = f"{pct:.2f}%"
    label = f"Stressed P&L ({result.scenario})"
    formula = [
        f"Scenario: {result.scenario}",
        f"Portfolio P&L = {result.portfolio_pnl:,.0f}",
        f"Portfolio impact = {topline}",
    ]
    worst = result.worst_positions[:3]
    formula += [f"  {w.ticker}: {w.pct_impact * 100:.2f}% of portfolio" for w in worst]
    detail = [
        {"ticker": p.ticker, "pnl_impact": p.pnl_impact, "pct_impact": p.pct_impact * 100.0}
        for p in sorted(result.positions, key=lambda x: x.pnl_impact)
    ]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=(
            f"Under {result.scenario}, portfolio P&L impact is {topline}. "
            f"Worst: {', '.join(w.ticker for w in worst) or 'n/a'}."
        ),
        models_used=[f"stress:{result.scenario}"],
        detail_rows=detail,
    )


def _run_garch(
    portfolio: EnrichedPortfolio,
    limits: RiskLimits,
    params: dict[str, Any],
) -> _ModelOutput:
    ticker = str(params.get("ticker") or "").strip()
    if not ticker and portfolio.positions:
        ticker = portfolio.positions[0].ticker
    result = run_garch(portfolio, ticker)
    topline = f"{result.vol_forecast_10d * 100:.2f}%"
    label = f"GARCH(1,1) 10-day vol forecast — {result.ticker}"
    formula = [
        f"GARCH(1,1) fit for {result.ticker}",
        f"ω = {result.omega:.6f}, α = {result.alpha:.4f}, β = {result.beta_param:.4f}",
        f"AIC = {result.aic:.2f}, BIC = {result.bic:.2f}",
        f"10-day vol forecast = {topline}",
        f"1-day conditional VaR (99%) = {result.conditional_var_1d * 100:.2f}%",
    ]
    detail = [{"day": i + 1, "vol": v} for i, v in enumerate(result.vol_forecast_series)]
    return _ModelOutput(
        topline_number=topline,
        topline_label=label,
        formula_breakdown=formula,
        explanation=(
            f"GARCH(1,1) on {result.ticker} forecasts {topline} volatility at day 10."
        ),
        models_used=["garch"],
        detail_rows=detail,
    )


def _finalize_explanation(
    query: str,
    request: str,
    draft: str,
    portfolio_summary: str,
    output: _ModelOutput,
) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return draft
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"User asked: {query}\n\n"
            f"Portfolio:\n{portfolio_summary}\n\n"
            f"Computed result: {output.topline_number} ({output.topline_label})\n"
            f"Draft explanation:\n{draft}\n\n"
            f"Write 2–3 sentences for a risk manager covering: {request}"
        )
        message = client.messages.create(
            model=anthropic_model(),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text if message.content else ""
        return text.strip() or draft
    except Exception as exc:
        logger.warning("Claude explanation failed: %s", exc)
        return draft


def _z_value(confidence: float) -> float:
    from scipy import stats

    return float(stats.norm.ppf(confidence))


def _routing_parameters(routing: RoutingInstruction, output: _ModelOutput) -> dict[str, Any]:
    params: dict[str, Any] = {"models_used": ", ".join(output.models_used)}
    for section, values in routing.parameters.items():
        if isinstance(values, dict):
            for k, v in values.items():
                params[f"{section}.{k}"] = v
        else:
            params[str(section)] = values
    return params


def _query_slug(query: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", query.lower())[:40].strip("_")
    return slug or "query"
