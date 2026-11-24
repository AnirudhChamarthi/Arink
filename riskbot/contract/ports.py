"""Ports: the interfaces between components (typing.Protocol, structural).

Dependency rule: every component imports only ``riskbot.contract``. Concrete classes meet these
protocols structurally; the composition root (``riskbot/app.py``) passes them to each other.

Which component implements which port
--------------------------------------
| Port               | Implemented by            | Consumed by                    |
|--------------------|---------------------------|--------------------------------|
| Model              | core.market / balance_sheet / climate | services (registry, executor) |
| ModelRegistry      | services                  | orchestration                  |
| VariationPlanner   | services                  | orchestration                  |
| VariationExecutor  | services                  | orchestration                  |
| Comparator         | services                  | orchestration                  |
| NumberVerifier     | services                  | orchestration                  |
| RunStore           | services                  | orchestration                  |
| Reporter           | services                  | orchestration                  |
| Assessor           | qualitative               | orchestration                  |
| RationaleDrafter   | orchestration (optional)  | orchestration                  |
| RunService         | orchestration             | api, mcp (and through api: web, WPF) |
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, runtime_checkable

from .types import (
    AuditEvent,
    CalcRequest,
    Comparison,
    DataQualityFinding,
    Dataset,
    FactorEdit,
    ModelOutput,
    ModelSpec,
    QualitativeAssessment,
    QuestionId,
    QuestionInfo,
    QuestionPlan,
    Report,
    ReviewSubmission,
    RunRecord,
    RunRequest,
    RunResult,
    SignOff,
    Trace,
    VariationResult,
    VariationSpec,
    VerifierFinding,
)


@runtime_checkable
class Model(Protocol):
    """One calculation from the catalogue. Pure: same (dataset, params, seed) -> same output.

    * ``params`` may be partial; call ``contract.conformance.resolve_params`` to apply defaults,
      validate and drop inapplicable parameters, and put the result in ``ModelOutput.params``.
    * Raise ``ValidationFailed`` for bad parameters or a dataset of the wrong kind / too short.
    * Every metric links to a step of one of the returned traces (``TraceBuilder.metric``).
    * No I/O, no network, no global state, no wall-clock dependence.
    """

    spec: ModelSpec

    def run(self, dataset: Dataset, params: dict[str, Any], seed: int) -> ModelOutput: ...


class ModelRegistry(Protocol):
    def register(self, model: Model) -> None: ...
    def get(self, model_id: str) -> Model: ...  # NotFound
    def specs(self, question: QuestionId | None = None) -> list[ModelSpec]: ...


class VariationPlanner(Protocol):
    def expand(self, plan: QuestionPlan, seed: int) -> list[VariationSpec]:
        """Cartesian product of grid dimensions (+ fixed), drop parameters whose ``applies_when`` is not met,
        de-duplicate by variation id, then extras (role='extra'). Seeds via ``hashing.derive_seed``.
        Raises ValidationFailed for unknown models/params/values and LimitExceeded above max_variations."""
        ...


class VariationExecutor(Protocol):
    def execute(self, spec: VariationSpec, dataset: Dataset) -> VariationResult:
        """Run one variation. Never raises for model errors: they are captured in ``VariationResult.error``.
        Checks the output with ``conformance.check_output`` and records violations as errors."""
        ...


class Comparator(Protocol):
    def compare(self, plan: QuestionPlan, results: list[VariationResult]) -> Comparison: ...


class NumberVerifier(Protocol):
    def check_outputs(self, results: list[VariationResult]) -> list[VerifierFinding]:
        """Every metric must equal the value of the trace step it links to (rel. tol 1e-9)."""
        ...

    def verify_text(self, location: str, text: str, results: list[VariationResult]) -> list[VerifierFinding]:
        """Extract every number in ``text`` (percentages, bp, currency, plain) and match it against metric
        values of ``results`` with unit-aware tolerance (rounding to the printed precision). Unmatched numbers
        give ``matched=False`` findings. Integers 1-5 used as ratings and years 1900-2100 are ignored."""
        ...


class Assessor(Protocol):
    def assess(
        self,
        question: QuestionId,
        dataset: Dataset,
        results: list[VariationResult],
        comparison: Comparison,
    ) -> QualitativeAssessment:
        """Pre-fill the question's rubric with deterministic rules (source='rule') citing evidence; factors with
        no rule are 'unassessed' with likelihood=impact=3 and control='adequate' and say so in the rationale."""
        ...

    def apply_edits(
        self, assessment: QualitativeAssessment, edits: list[FactorEdit], reviewer: str, at: dt.datetime
    ) -> QualitativeAssessment:
        """Apply analyst edits, recompute ratings with ``rules.rate``, set source='analyst', log Overrides.
        Unknown factor ids raise ValidationFailed."""
        ...


class RationaleDrafter(Protocol):
    def draft(self, assessment: QualitativeAssessment, results: list[VariationResult]) -> dict[str, str]:
        """factor_id -> drafted rationale. Output is verified before use; unverifiable numbers are rejected."""
        ...


class RunStore(Protocol):
    def create_run(self, record: RunRecord, request: RunRequest) -> None: ...
    def update_run(self, record: RunRecord) -> None: ...
    def get_run(self, run_id: str) -> RunRecord: ...  # NotFound
    def get_request(self, run_id: str) -> RunRequest: ...  # NotFound
    def list_runs(self, limit: int = 100) -> list[RunRecord]: ...  # newest first
    def save_result(self, result: RunResult) -> None: ...  # also indexes every trace by trace_id
    def get_result(self, run_id: str) -> RunResult: ...  # NotFound if no result yet
    def get_trace(self, trace_id: str) -> Trace: ...  # NotFound
    def save_signoff(self, run_id: str, signoff: SignOff) -> None: ...
    def get_signoff(self, run_id: str) -> SignOff | None: ...
    def append_audit(self, event: AuditEvent) -> None: ...
    def audit_log(self, run_id: str) -> list[AuditEvent]: ...  # oldest first


class Reporter(Protocol):
    def build(self, result: RunResult, signoff: SignOff | None) -> Report:
        """Headline sentences built only from comparison/metric values (so they verify), plus Markdown with
        the comparison tables, the assessment (marked as judgment) and the sign-off."""
        ...


class RunService(Protocol):
    """The single facade every adapter talks to. Status flow:
    pending -> running -> awaiting_review -> approved | rejected; any -> failed on error."""

    def questions(self) -> list[QuestionInfo]: ...
    def list_models(self, question: QuestionId | None = None) -> list[ModelSpec]: ...
    def sample_dataset(self, question: QuestionId) -> Dataset: ...
    def validate(self, dataset: Dataset) -> list[DataQualityFinding]: ...
    def calc(self, request: CalcRequest) -> ModelOutput: ...  # ValidationFailed / NotFound
    def start_run(self, request: RunRequest, *, wait: bool = False) -> RunRecord:
        """wait=False returns at once (pending/running); wait=True returns once awaiting_review or failed."""
        ...
    def list_runs(self, limit: int = 100) -> list[RunRecord]: ...
    def get_run(self, run_id: str) -> RunRecord: ...
    def get_result(self, run_id: str) -> RunResult: ...  # Conflict if not finished
    def get_trace(self, trace_id: str) -> Trace: ...
    def submit_review(self, run_id: str, review: ReviewSubmission) -> RunRecord: ...  # Conflict unless awaiting_review
    def get_report(self, run_id: str) -> Report: ...  # Conflict if not finished
    def audit_log(self, run_id: str) -> list[AuditEvent]: ...
