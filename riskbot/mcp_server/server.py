"""The Riskbot MCP server: tools, resources and prompts over ``RunService`` (CONTRACT.md 4.6 and 6.2).

Design
------
* **Thin adapter.** Every tool maps to exactly one ``RunService`` method; no risk logic lives here.
* **Contract types on the wire.** Tool arguments are contract models (``Dataset``, ``QuestionPlan``,
  ``QuestionId`` ...), so the generated JSON Schema is complete, and tools return contract models as
  structured output. Tools that return a list or a union (``Dataset``) are wrapped by the SDK as
  ``{"result": ...}`` because MCP structured content must be a JSON object.
* **Read-only by default.** Every tool is annotated ``readOnlyHint=True, idempotentHint=True,
  openWorldHint=False`` except ``start_run`` (``readOnlyHint=False, destructiveHint=False``), the only
  state-changing tool. There is deliberately no review / approve / sign-off tool: that is human-only.
* **Errors.** ``RiskbotError`` subclasses become tool-error results ``"<code>: <message>"``
  (``is_error=True``); pydantic validation errors raised while building requests become
  ``validation_failed``; anything else is logged server-side and surfaced as ``"internal: ..."`` without
  a stack trace. Arguments that do not match the input schema are rejected by the SDK itself before the
  tool runs (also ``is_error=True``, message ``"Error executing tool <name>: <pydantic summary>"``).
  Resource reads raise ``ResourceNotFoundError`` / ``ResourceError`` (JSON-RPC errors) with the same
  ``"<code>: <message>"`` text.
* **Limits.** ``catalog.LIMITS`` is checked before the service is called (``limit_exceeded``).
* **Blocking calls.** Tool functions are synchronous; the SDK runs them in a worker thread, so a
  ``start_run(wait=True)`` that takes a while does not block the event loop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from riskbot.contract import CONTRACT_VERSION, catalog
from riskbot.contract.errors import NotFound, RiskbotError, ValidationFailed
from riskbot.contract.ports import RunService
from riskbot.contract.types import (
    CalcRequest,
    DataQualityFinding,
    Dataset,
    ModelOutput,
    ModelSpec,
    QuestionId,
    QuestionInfo,
    QuestionPlan,
    Report,
    RunRecord,
    RunRequest,
    RunResult,
    Trace,
)

from . import limits
from .guidance import PROMPTS, SERVER_INSTRUCTIONS, render_prompt
from .rendering import render_trace

__all__ = ["create_server", "READ_ONLY", "STATE_CHANGING", "TOOL_NAMES"]

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_SEED: int = RunRequest.model_fields["seed"].default

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
"""Annotations for every tool except ``start_run``: no side effects, safe to retry, closed world."""

STATE_CHANGING = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                                 openWorldHint=False)
"""Annotations for ``start_run``: creates a new run each call, never deletes or overwrites anything."""

TOOL_NAMES = (
    "list_questions", "list_models", "get_sample_dataset", "validate_dataset", "calculate",
    "start_run", "run_status", "run_result", "get_trace", "get_report",
)

# --------------------------------------------------------------------------------------------
# Argument types (contract types with descriptions, so the JSON Schema is self-explanatory)
# --------------------------------------------------------------------------------------------

QuestionArg = Annotated[QuestionId, Field(description="Question id: q1_market, q2_balance_sheet or q3_transition.")]
DatasetArg = Annotated[Dataset, Field(description="Input dataset; `kind` selects market, balance_sheet or climate. "
                                                  "Use get_sample_dataset to see the expected shape.")]
RunIdArg = Annotated[str, Field(min_length=1, description="Run id returned by start_run.")]
TraceIdArg = Annotated[str, Field(min_length=1, description="Trace id from Metric.trace_id, e.g. 'q1.var-1a2b3c4d5e6f'.")]
SeedArg = Annotated[int, Field(description="Random seed; the same inputs and seed give the same results.")]


# --------------------------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------------------------


def _validation_summary(exc: ValidationError) -> str:
    """Compact, value-free summary of a pydantic error (field paths and messages only)."""
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "input"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    more = len(exc.errors()) - len(parts)
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")


def error_message(exc: BaseException) -> str:
    """The client-facing message for an exception: ``'<code>: <message>'``, never a stack trace."""
    if isinstance(exc, RiskbotError):
        return f"{exc.code}: {exc.message}"
    if isinstance(exc, ValidationError):
        return f"{ValidationFailed.code}: {_validation_summary(exc)}"
    return "internal: unexpected server error (details in the server log)"


def tool_error(message: str) -> CallToolResult:
    """An MCP tool-error result (``is_error=True``) whose only content is ``message``."""
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def _tool_call(name: str, fn: Callable[[], T]) -> T:
    """Run ``fn``; translate failures into a tool-error result (``is_error=True``) for the client.

    The error is *returned* as a ``CallToolResult`` rather than raised as ``ToolError`` because the SDK
    prefixes raised tool errors with ``"Error executing tool <name>: "``; returning it keeps the message
    exactly ``"<code>: <message>"`` as the contract requires. The SDK passes an ``is_error`` result through
    without validating it against the output schema, hence the ``cast``.
    """
    try:
        return fn()
    except (RiskbotError, ValidationError) as exc:
        message = error_message(exc)
        logger.info("tool %s failed: %s", name, message)
    except Exception:
        logger.exception("tool %s raised an unexpected exception", name)
        message = error_message(Exception())
    return cast(T, tool_error(message))


def _resource_call(uri: str, fn: Callable[[], T]) -> T:
    """Run ``fn`` for a resource read; ``NotFound`` maps to ``ResourceNotFoundError``."""
    try:
        return fn()
    except NotFound as exc:
        raise ResourceNotFoundError(error_message(exc)) from None
    except RiskbotError as exc:
        raise ResourceError(error_message(exc)) from None
    except Exception:
        logger.exception("resource %s raised an unexpected exception", uri)
        raise ResourceError(error_message(Exception())) from None


def _check_kind(question: QuestionId, dataset: Dataset) -> None:
    """The dataset kind must match the question (catalogue), else ``ValidationFailed``."""
    expected = catalog.QUESTIONS[question].dataset_kind.value
    if dataset.kind != expected:
        raise ValidationFailed(f"question {question.value} needs a {expected} dataset, got kind={dataset.kind!r}",
                               expected=expected, actual=dataset.kind)


# --------------------------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------------------------


def create_server(service: RunService) -> MCPServer:
    """Build the Riskbot MCP server over ``service``.

    The composition root launches it with ``python -m riskbot.app mcp`` (stdio transport); tests use
    ``mcp.Client(server)`` in process with ``contract.fakes.FakeRunService``.
    """
    server: MCPServer = MCPServer(
        name="riskbot",
        title="Riskbot",
        description="Verifiable risk analysis: variation sets, traces and reports.",
        instructions=SERVER_INSTRUCTIONS,
        version=CONTRACT_VERSION,
    )

    # ---------------------------------------------------------------- tools: catalogue

    @server.tool(
        title="List questions",
        annotations=READ_ONLY,
        description="List the three risk questions Riskbot answers, each with its dataset kind and default "
                    "variation plan (grid dimensions and extra runs).",
    )
    def list_questions() -> list[QuestionInfo]:
        return _tool_call("list_questions", service.questions)

    @server.tool(
        title="List models",
        annotations=READ_ONLY,
        description="List model specifications (parameters with defaults/choices/ranges, metrics with units, "
                    "labels), optionally only those of one question.",
    )
    def list_models(
        question: Annotated[QuestionId | None, Field(description="Filter by question id; omit for all models.")] = None,
    ) -> list[ModelSpec]:
        return _tool_call("list_models", lambda: service.list_models(question))

    @server.tool(
        title="Get sample dataset",
        annotations=READ_ONLY,
        description="Return the built-in sample dataset for a question. Sample datasets are SYNTHETIC "
                    "(synthetic=true) and must be described as synthetic when reporting results. Returned as "
                    "{\"result\": Dataset}.",
    )
    def get_sample_dataset(question: QuestionArg) -> Dataset:
        return _tool_call("get_sample_dataset", lambda: service.sample_dataset(question))

    @server.tool(
        title="Validate dataset",
        annotations=READ_ONLY,
        description="Validate a dataset (schema plus the question's data-quality model) and return the "
                    "data-quality findings (check, severity, field, subject, count, message).",
    )
    def validate_dataset(dataset: DatasetArg) -> list[DataQualityFinding]:
        def call() -> list[DataQualityFinding]:
            limits.check_dataset(dataset)
            return service.validate(dataset)

        return _tool_call("validate_dataset", call)

    # ---------------------------------------------------------------- tools: calculation

    @server.tool(
        title="Calculate one model",
        annotations=READ_ONLY,
        description="Run a single catalogue model synchronously and return its output: effective params, "
                    "metrics (each with unit, trace_id and trace_step), labels, traces and findings. Pure and "
                    "deterministic: the same dataset, params and seed give the same output.",
    )
    def calculate(
        model_id: Annotated[str, Field(min_length=1, description="Model id from list_models, e.g. 'q1.var'.")],
        dataset: DatasetArg,
        params: Annotated[dict[str, Any] | None, Field(
            description="Model parameters (see list_models); omitted ones take their defaults.")] = None,
        seed: SeedArg = DEFAULT_SEED,
    ) -> ModelOutput:
        def call() -> ModelOutput:
            limits.check_dataset(dataset)
            return service.calc(CalcRequest(model_id=model_id, dataset=dataset, params=params or {}, seed=seed))

        return _tool_call("calculate", call)

    @server.tool(
        title="Start a run",
        annotations=STATE_CHANGING,
        description="Start an analysis run: expand the variation plan, run every variation, compare them and "
                    "pre-fill the qualitative assessment. Unlike the REST API, wait defaults to TRUE here: the "
                    "call returns once the run is awaiting_review or failed, so run_result can be called next. "
                    "With wait=false it returns at once (pending/running); poll run_status. Omit plan to use the "
                    "question's default plan. Each call creates a new run; the run then needs human review "
                    "(not available over MCP).",
    )
    def start_run(
        question: QuestionArg,
        dataset: DatasetArg,
        plan: Annotated[QuestionPlan | None, Field(
            description="Variation plan; omit to use the question's default plan (see list_questions).")] = None,
        seed: SeedArg = DEFAULT_SEED,
        wait: Annotated[bool, Field(
            description="Block until the run is awaiting_review or failed (default true).")] = True,
    ) -> RunRecord:
        def call() -> RunRecord:
            _check_kind(question, dataset)
            limits.check_dataset(dataset)
            if plan is not None:
                if plan.question != question:
                    raise ValidationFailed(f"plan.question {plan.question.value} does not match question "
                                           f"{question.value}")
                limits.check_plan(plan)
            request = RunRequest(question=question, dataset=dataset, plan=plan, seed=seed)
            return service.start_run(request, wait=wait)

        return _tool_call("start_run", call)

    # ---------------------------------------------------------------- tools: results

    @server.tool(
        title="Run status",
        annotations=READ_ONLY,
        description="Return the run record: status (pending, running, awaiting_review, approved, rejected, "
                    "failed), dataset name, synthetic flag, number of variations and any error.",
    )
    def run_status(run_id: RunIdArg) -> RunRecord:
        return _tool_call("run_status", lambda: service.get_run(run_id))

    @server.tool(
        title="Run result",
        annotations=READ_ONLY,
        description="Return the full result of a finished run: plan, every variation (params, metrics with "
                    "trace ids, labels or error), the comparison (metric ranges, method spread, sensitivity, "
                    "conclusion flips, break-evens, label counts), the qualitative assessment (judgment) and "
                    "verifier findings. Conflict while the run is pending, running or failed.",
    )
    def run_result(run_id: RunIdArg) -> RunResult:
        return _tool_call("run_result", lambda: service.get_result(run_id))

    @server.tool(
        title="Get trace",
        annotations=READ_ONLY,
        description="Return the step-by-step working behind a number: assumptions, steps (LaTeX formula, "
                    "substitution, value, unit, table) and the input hash. The Markdown rendering is the "
                    "resource riskbot://traces/{trace_id}.",
    )
    def get_trace(trace_id: TraceIdArg) -> Trace:
        return _tool_call("get_trace", lambda: service.get_trace(trace_id))

    @server.tool(
        title="Get report",
        annotations=READ_ONLY,
        description="Return the run report: verified headline sentences, comparison, assessment, sign-off (if a "
                    "human has reviewed it) and the Markdown text (also at riskbot://reports/{run_id}). Conflict "
                    "while the run is pending, running or failed.",
    )
    def get_report(run_id: RunIdArg) -> Report:
        return _tool_call("get_report", lambda: service.get_report(run_id))

    # ---------------------------------------------------------------- resources

    @server.resource(
        "riskbot://models",
        name="models",
        title="Model catalogue",
        description="Every model specification (parameters, metrics, units, labels) as JSON.",
        mime_type="application/json",
    )
    def models_resource() -> str:
        specs = _resource_call("riskbot://models", lambda: service.list_models(None))
        return json.dumps([s.model_dump(mode="json") for s in specs], indent=2)

    @server.resource(
        "riskbot://traces/{trace_id}",
        name="trace",
        title="Trace (Markdown)",
        description="A calculation trace rendered as Markdown: assumptions, numbered steps with $$formula$$, "
                    "substitution, value and unit, tables, warnings and input hash.",
        mime_type="text/markdown",
    )
    def trace_resource(trace_id: str) -> str:
        uri = f"riskbot://traces/{trace_id}"
        return render_trace(_resource_call(uri, lambda: service.get_trace(trace_id)))

    @server.resource(
        "riskbot://reports/{run_id}",
        name="report",
        title="Run report (Markdown)",
        description="The Markdown report of a finished run.",
        mime_type="text/markdown",
    )
    def report_resource(run_id: str) -> str:
        uri = f"riskbot://reports/{run_id}"
        return _resource_call(uri, lambda: service.get_report(run_id)).markdown

    # ---------------------------------------------------------------- prompts

    for prompt_name, (_question, prompt_title, _focus) in PROMPTS.items():
        _register_prompt(server, prompt_name, prompt_title)

    return server


def _register_prompt(server: MCPServer, name: str, title: str) -> None:
    """Register one guidance prompt taking an optional ``dataset_hint`` argument."""

    def prompt(
        dataset_hint: Annotated[str | None, Field(
            description="Optional description of the user's dataset; omit to use the synthetic sample.")] = None,
    ) -> str:
        return render_prompt(name, dataset_hint)

    prompt.__doc__ = (f"{title}: which Riskbot tools to call and how to report (numbers only from tools, "
                      "each with its trace_id). Optional dataset_hint describes the user's data; without it the "
                      "synthetic sample is used.")
    server.prompt(name=name, title=title, description=prompt.__doc__)(prompt)
