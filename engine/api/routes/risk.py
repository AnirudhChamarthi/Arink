from fastapi import APIRouter, HTTPException

from models.garch import run_garch
from models.greeks import run_greeks
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import run_var
from reports.excel_writer import validate_report_path
from reports.master_report import generate_full_report
from reports.stress_report import stress_result_with_report
from schemas.contract import (
    FullReportRequest,
    FullReportResult,
    GarchRequest,
    GarchResult,
    GreeksRequest,
    PortfolioGreeks,
    StressRequest,
    StressResult,
    SustainabilityRequest,
    SustainabilityResult,
    VarRequest,
    VarResult,
)
from services.portfolio_resolve import resolve_enriched_portfolio

router = APIRouter(prefix="/risk", tags=["Risk"])


@router.post("/var", response_model=VarResult)
def post_var(body: VarRequest) -> VarResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        return run_var(
            portfolio,
            body.method,
            body.confidence,
            body.horizon_days,
            body.n_sims,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/greeks", response_model=PortfolioGreeks)
def post_greeks(body: GreeksRequest) -> PortfolioGreeks:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        return run_greeks(portfolio)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/stress", response_model=StressResult)
def post_stress(body: StressRequest) -> StressResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        result = run_stress(portfolio, body.scenario, body.custom_shocks)
        return stress_result_with_report(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sustainability", response_model=SustainabilityResult)
def post_sustainability(body: SustainabilityRequest) -> SustainabilityResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        return run_sustainability(
            portfolio,
            body.exclusion_filters,
            include_carbon_var=body.include_carbon_var,
            carbon_price_shock=body.carbon_price_shock,
            run_exclusion_check=body.run_exclusion_check,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/full-report", response_model=FullReportResult)
def post_full_report(body: FullReportRequest) -> FullReportResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        path, summary = generate_full_report(
            portfolio,
            method=body.method,
            confidence=body.confidence,
            horizon_days=body.horizon_days,
            stress_scenario=body.stress_scenario,
            exclusion_filters=body.exclusion_filters,
        )
        safe_path = validate_report_path(path)
        return FullReportResult(
            excel_report_path=safe_path,
            summary_text=summary,
            portfolio_name=portfolio.portfolio_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/garch", response_model=GarchResult)
def post_garch(body: GarchRequest) -> GarchResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        return run_garch(portfolio, body.ticker)
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
