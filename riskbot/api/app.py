"""FastAPI application over the ``RunService`` port (CONTRACT.md sections 4.5 and 6.1).

The app is a thin adapter: it parses and validates requests into contract types, enforces the HTTP-level
limits, calls exactly one ``RunService`` method per route and serialises the contract type it returns.
It holds no state of its own besides the service reference, so several apps can share one service.

Middleware order (outermost first): CORS -> internal-error guard -> body-size limit -> FastAPI routing
(with the ``ErrorBody`` exception handlers). CORS is outermost so even 413 and 500 responses carry the
CORS headers the web UI needs to read them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, FastAPI, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from riskbot.contract import CONTRACT_VERSION
from riskbot.contract.ports import RunService
from riskbot.contract.types import (
    AuditEvent,
    CalcRequest,
    DataQualityFinding,
    Dataset,
    ErrorBody,
    ModelOutput,
    ModelSpec,
    QuestionId,
    QuestionInfo,
    Report,
    ReviewSubmission,
    RunRecord,
    RunRequest,
    RunResult,
    Trace,
)

from .errors import InternalErrorMiddleware, install_error_handlers
from .limits import BodySizeLimitMiddleware, check_dataset_limits, check_plan_limits

PREFIX = "/v2"
DEFAULT_CORS_ORIGINS = ["http://localhost:5173"]
API_TITLE = "Riskbot v2 API"


class Health(BaseModel):
    """Liveness probe body: ``{"status": "ok", "contract_version": ...}``."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"
    contract_version: str


def _errors(*statuses: int) -> dict[int | str, dict[str, object]]:
    """OpenAPI ``responses`` entries documenting ``ErrorBody`` for the given statuses (plus 500)."""
    descriptions = {
        404: "Unknown run, trace or model (`not_found`).",
        409: "Run is in the wrong state (`conflict`).",
        413: "Body above 10 MB or dataset/plan above `catalog.LIMITS` (`limit_exceeded`).",
        422: "Invalid request: body, path or query (`validation_failed`).",
        500: "Unexpected error (`internal`); details are logged, not returned.",
    }
    return {s: {"model": ErrorBody, "description": descriptions[s]} for s in (*statuses, 500)}


RunId = Annotated[str, Path(description="Run id returned by `POST /v2/runs`.")]


def _build_router(service: RunService) -> APIRouter:
    """Create the ``/v2`` router bound to ``service``. Route functions are sync (``def``) because the
    service is blocking; FastAPI runs them in its thread pool."""
    r = APIRouter(prefix=PREFIX)

    @r.get("/health", response_model=Health, tags=["meta"], summary="Liveness probe")
    def health() -> Health:
        """Return `ok` and the contract version this API implements. Does not touch the service."""
        return Health(contract_version=CONTRACT_VERSION)

    @r.get("/questions", response_model=list[QuestionInfo], tags=["catalogue"], responses=_errors(),
           summary="List the questions")
    def questions() -> list[QuestionInfo]:
        """The three risk questions with their dataset kind and default variation plan."""
        return service.questions()

    @r.get("/models", response_model=list[ModelSpec], tags=["catalogue"], responses=_errors(422),
           summary="List model specs")
    def list_models(
        question: Annotated[QuestionId | None, Query(description="Only models of this question.")] = None,
    ) -> list[ModelSpec]:
        """Catalogue entries (parameters, metrics, labels) of every registered model, optionally filtered."""
        return service.list_models(question)

    @r.get("/samples/{question}", response_model=Dataset, tags=["datasets"], responses=_errors(422),
           summary="Synthetic sample dataset")
    def sample_dataset(question: QuestionId) -> Dataset:
        """The deterministic synthetic sample dataset for a question (`synthetic` is true)."""
        return service.sample_dataset(question)

    @r.post("/datasets/validate", response_model=list[DataQualityFinding], tags=["datasets"],
            responses=_errors(413, 422), summary="Validate a dataset")
    def validate(dataset: Annotated[Dataset, Body(discriminator="kind")]) -> list[DataQualityFinding]:
        """Schema validation (by FastAPI) plus the question's data-quality model; returns its findings."""
        check_dataset_limits(dataset)
        return service.validate(dataset)

    @r.post("/calc", response_model=ModelOutput, tags=["calculations"], responses=_errors(404, 413, 422),
            summary="Run one model")
    def calc(request: CalcRequest) -> ModelOutput:
        """Run a single model synchronously and return its metrics, labels and traces."""
        check_dataset_limits(request.dataset)
        return service.calc(request)

    @r.post("/runs", response_model=RunRecord, status_code=202, tags=["runs"], responses=_errors(413, 422),
            summary="Start a run")
    def start_run(request: RunRequest, response: Response) -> RunRecord:
        """Start a variation run in the background (`wait=False`) and return its record at once.

        Poll `GET /v2/runs/{run_id}` until the status is `awaiting_review` or `failed`. The `Location`
        header points at the run.
        """
        check_dataset_limits(request.dataset)
        check_plan_limits(request.plan)
        record = service.start_run(request, wait=False)
        response.headers["Location"] = f"{PREFIX}/runs/{record.run_id}"
        return record

    @r.get("/runs", response_model=list[RunRecord], tags=["runs"], responses=_errors(422), summary="List runs")
    def list_runs(
        limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of runs, newest first.")] = 100,
    ) -> list[RunRecord]:
        """Most recent runs first."""
        return service.list_runs(limit)

    @r.get("/runs/{run_id}", response_model=RunRecord, tags=["runs"], responses=_errors(404, 422),
           summary="Run status")
    def get_run(run_id: RunId) -> RunRecord:
        """The run record, including its current status."""
        return service.get_run(run_id)

    @r.get("/runs/{run_id}/result", response_model=RunResult, tags=["runs"], responses=_errors(404, 409, 422),
           summary="Run result")
    def get_result(run_id: RunId) -> RunResult:
        """Variations, comparison and qualitative assessment. 409 while pending/running or if failed."""
        return service.get_result(run_id)

    @r.get("/runs/{run_id}/audit", response_model=list[AuditEvent], tags=["runs"], responses=_errors(404, 422),
           summary="Audit log")
    def audit_log(run_id: RunId) -> list[AuditEvent]:
        """Every recorded event of the run, oldest first."""
        return service.audit_log(run_id)

    @r.post("/runs/{run_id}/review", response_model=RunRecord, tags=["review"],
            responses=_errors(404, 409, 413, 422), summary="Review and sign off")
    def submit_review(run_id: RunId, review: ReviewSubmission) -> RunRecord:
        """Approve or reject a run awaiting review, optionally editing rubric factors. 409 otherwise."""
        return service.submit_review(run_id, review)

    @r.get(
        "/runs/{run_id}/report",
        response_model=Report,
        tags=["runs"],
        summary="Run report (JSON or Markdown)",
        responses={
            200: {
                "description": "`Report` as JSON, or its Markdown when `format=md`.",
                "content": {"text/markdown": {"schema": {"type": "string"}}},
            },
            **_errors(404, 409, 422),
        },
    )
    def get_report(
        run_id: RunId,
        format: Annotated[Literal["json", "md"], Query(description="`md` returns `text/markdown`.")] = "json",
    ) -> Report | Response:
        """The run report. 409 while the run is pending, running or failed."""
        report = service.get_report(run_id)
        if format == "md":
            return Response(content=report.markdown, media_type="text/markdown; charset=utf-8")
        return report

    @r.get("/traces/{trace_id}", response_model=Trace, tags=["traces"], responses=_errors(404, 422),
           summary="Calculation trace")
    def get_trace(trace_id: Annotated[str, Path(description="'<model_id>-<12 hex>[-suffix]'.")]) -> Trace:
        """The step-by-step working (formula, substitution, value) behind a set of metrics."""
        return service.get_trace(trace_id)

    return r


def create_app(service: RunService, *, cors_origins: list[str] | None = None) -> FastAPI:
    """Build the Riskbot v2 REST API over ``service``.

    Args:
        service: any implementation of ``contract.ports.RunService`` (LangGraph orchestration in
            production, ``contract.fakes.FakeRunService`` in tests).
        cors_origins: allowed browser origins; defaults to ``["http://localhost:5173"]`` (Vite dev server).

    Returns:
        A FastAPI app with routes under ``/v2``, OpenAPI at ``/v2/openapi.json`` and docs at ``/v2/docs``.
        Serving it (uvicorn) is the composition root's job.
    """
    app = FastAPI(
        title=API_TITLE,
        version=CONTRACT_VERSION,
        description=(
            "Verifiable risk analysis over the Riskbot v2 contract. Every error is an `ErrorBody` "
            "`{code, message, details}` with the HTTP status of its contract exception."
        ),
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=f"{PREFIX}/docs",
        redoc_url=f"{PREFIX}/redoc",
        separate_input_output_schemas=False,
    )
    app.state.service = service
    install_error_handlers(app)
    app.include_router(_build_router(service))

    # add_middleware prepends: the last added is the outermost.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(InternalErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEFAULT_CORS_ORIGINS if cors_origins is None else cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Location"],
    )
    return app
