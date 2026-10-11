from fastapi import APIRouter, HTTPException

from nlp.executor import run_nlq
from reports.excel_writer import validate_report_path
from schemas.contract import NlqRequest, NlqResult
from services.portfolio_resolve import resolve_enriched_portfolio

router = APIRouter(tags=["NLQ"])

_NLQ_FAILURE_MESSAGE = "NLQ processing failed. Check engine logs for details."
_logger = __import__("logging").getLogger(__name__)


@router.post("/nlq", response_model=NlqResult)
def post_nlq(body: NlqRequest) -> NlqResult:
    try:
        portfolio = resolve_enriched_portfolio(
            portfolio_session_id=body.portfolio_session_id,
            portfolio=body.portfolio,
        )
        result = run_nlq(body.query, portfolio, body.limits)
        safe_path = validate_report_path(result.excel_report_path)
        return result.model_copy(update={"excel_report_path": safe_path})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("NLQ failed")
        raise HTTPException(status_code=502, detail=_NLQ_FAILURE_MESSAGE) from exc
