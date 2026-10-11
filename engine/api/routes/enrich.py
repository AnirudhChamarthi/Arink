from fastapi import APIRouter, HTTPException, Query

from schemas.contract import EnrichRequest, EnrichResponse, ResponseDetail
from services.enrich import enrich_and_respond

router = APIRouter(tags=["Data"])


@router.post("/enrich", response_model=EnrichResponse)
def post_enrich(
    body: EnrichRequest,
    response_detail: ResponseDetail = Query(
        default=ResponseDetail.DISPLAY,
        description="display = blotter fields only; full = includes returns_252d and options_chain",
    ),
) -> EnrichResponse:
    try:
        return enrich_and_respond(body, response_detail)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
