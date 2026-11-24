"""``OrchestratedRunService``: the ``ports.RunService`` facade over the LangGraph run graph.

Responsibilities
----------------
* Synchronous validation in ``start_run`` (dataset kind, ``catalog.LIMITS``, plan/question match, plan
  expansion) so bad requests fail before a run exists.
* Run lifecycle: ``pending -> running -> awaiting_review -> approved | rejected``; ``failed`` from any
  non-terminal state. Every transition is written to the ``RunStore`` with an ``AuditEvent``.
* Threading: ``start_run(wait=False)`` drives the graph in a daemon thread; ``wait=True`` drives it in
  the caller's thread and returns once the graph pauses for review (or fails). A per-run re-entrant lock
  is held while the graph is being driven, so ``submit_review`` cannot resume a run whose interrupt has
  not been checkpointed yet. Different runs never share a lock.
* Read-side methods (questions, models, samples, traces, audit) delegate to the catalogue, registry and store.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from riskbot.contract import CONTRACT_VERSION, catalog, ports
from riskbot.contract.errors import Conflict, LimitExceeded, NotFound, RiskbotError
from riskbot.contract.hashing import run_input_hash
from riskbot.contract.types import (
    AuditEvent,
    CalcRequest,
    DataQualityFinding,
    Dataset,
    ModelOutput,
    ModelSpec,
    QuestionId,
    QuestionInfo,
    Report,
    ReviewSubmission,
    RunRecord,
    RunRequest,
    RunResult,
    RunStatus,
    Severity,
    Trace,
)

from .graph import GraphDeps, RunState, build_graph, utcnow
from .validation import check_dataset_kind, check_limits, dataset_kind, question_for_kind, resolve_plan

#: Allowed status transitions (``failed`` is reachable from every non-terminal state).
TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.AWAITING_REVIEW, RunStatus.FAILED},
    RunStatus.AWAITING_REVIEW: {RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.FAILED},
}
_NOT_FINISHED = (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED)
_DEFAULT_SEED = 20261123  # same default as CalcRequest / RunRequest


def _message(exc: BaseException) -> str:
    """Contract errors keep their message; anything else is prefixed with its type."""
    if isinstance(exc, RiskbotError):
        return exc.message
    return f"{type(exc).__name__}: {exc}"


class OrchestratedRunService:
    """Implements every method of ``ports.RunService``. Build it with ``riskbot.orchestration.run_service``."""

    def __init__(
        self,
        *,
        registry: ports.ModelRegistry,
        planner: ports.VariationPlanner,
        executor: ports.VariationExecutor,
        comparator: ports.Comparator,
        verifier: ports.NumberVerifier,
        store: ports.RunStore,
        reporter: ports.Reporter,
        assessor: ports.Assessor,
        samples: dict[QuestionId, Callable[[], Dataset]],
        drafter: ports.RationaleDrafter | None = None,
        checkpoint_path: str = ":memory:",
    ) -> None:
        self.registry, self.planner, self.executor = registry, planner, executor
        self.comparator, self.verifier, self.store = comparator, verifier, store
        self.reporter, self.assessor, self.drafter = reporter, assessor, drafter
        self.samples = dict(samples)
        self._conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._conn)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        deps = GraphDeps(store=store, planner=planner, executor=executor, comparator=comparator, verifier=verifier,
                         reporter=reporter, assessor=assessor, drafter=drafter, transition=self._transition,
                         audit=self._audit)
        self.graph = build_graph(deps, self.checkpointer)

    # ------------------------------------------------------------------------------------------
    # Internal: locks, status and audit
    # ------------------------------------------------------------------------------------------

    def _lock(self, run_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.RLock())

    def _audit(self, run_id: str, event: str, *, actor: str = "system", detail: dict[str, Any] | None = None) -> None:
        self.store.append_audit(AuditEvent(run_id=run_id, at=utcnow(), actor=actor, event=event, detail=detail or {}))

    def _transition(self, run_id: str, status: RunStatus, *, actor: str = "system", error: str | None = None,
                    detail: dict[str, Any] | None = None) -> RunRecord:
        """Move a run to ``status`` (checked against ``TRANSITIONS``), persist it and audit it."""
        with self._lock(run_id):
            rec = self.store.get_run(run_id)
            if status not in TRANSITIONS.get(rec.status, set()):
                raise Conflict(f"run {run_id}: cannot move from {rec.status.value} to {status.value}")
            new = rec.model_copy(update={"status": status, "updated_at": utcnow(),
                                         "error": error if status == RunStatus.FAILED else rec.error})
            self.store.update_run(new)
            info: dict[str, Any] = {"from": rec.status.value, "to": status.value, **(detail or {})}
            if error:
                info["error"] = error
            self._audit(run_id, "status_changed", actor=actor, detail=info)
            return new

    def _fail(self, run_id: str, exc: BaseException) -> None:
        """Mark a run failed; never raises (used from background threads)."""
        try:
            if self.store.get_run(run_id).status in TRANSITIONS:
                self._transition(run_id, RunStatus.FAILED, error=_message(exc))
        except Exception:  # pragma: no cover - the store itself is broken; nothing more we can do
            pass

    def _config(self, run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    def _drive(self, run_id: str, graph_input: Any) -> None:
        """Run the graph until it pauses (interrupt) or ends. Any exception fails the run."""
        with self._lock(run_id):
            try:
                self.graph.invoke(graph_input, self._config(run_id), durability="sync")
            except Exception as exc:
                self._fail(run_id, exc)

    # ------------------------------------------------------------------------------------------
    # Catalogue, models, datasets
    # ------------------------------------------------------------------------------------------

    def questions(self) -> list[QuestionInfo]:
        return list(catalog.QUESTIONS.values())

    def list_models(self, question: QuestionId | None = None) -> list[ModelSpec]:
        return self.registry.specs(question)

    def sample_dataset(self, question: QuestionId) -> Dataset:
        factory = self.samples.get(QuestionId(question))
        if factory is None:
            raise NotFound(f"no sample dataset for question {QuestionId(question).value}")
        return factory()

    def validate(self, dataset: Dataset) -> list[DataQualityFinding]:
        """Run the ``*.data_quality`` model of the dataset's question and return its findings.

        Pydantic validation has already happened when ``dataset`` was constructed. Size limits raise
        ``LimitExceeded``. A failing data-quality model yields an error finding instead of raising.
        """
        check_limits(dataset)
        question = question_for_kind(dataset_kind(dataset))
        dq = [s.model_id for s in self.registry.specs(question) if s.model_id.endswith(".data_quality")]
        if not dq:
            return [DataQualityFinding(check="data_quality_model_missing", severity=Severity.ERROR, field="dataset",
                                       message=f"no data-quality model registered for {question.value}")]
        try:
            out = self.registry.get(dq[0]).run(dataset, {}, _DEFAULT_SEED)
        except Exception as exc:
            return [DataQualityFinding(check="data_quality_model_failed", severity=Severity.ERROR, field="dataset",
                                       message=f"{dq[0]} failed: {_message(exc)}")]
        return list(out.findings)

    def calc(self, request: CalcRequest) -> ModelOutput:
        """Run one model synchronously after the same dataset-kind and limit checks as a run."""
        model = self.registry.get(request.model_id)  # NotFound propagates
        check_dataset_kind(request.dataset, model.spec.dataset_kind, f"model {request.model_id}")
        check_limits(request.dataset)
        try:
            return model.run(request.dataset, request.params, request.seed)
        except RiskbotError:
            raise
        except Exception as exc:
            raise RiskbotError(f"{request.model_id} failed: {_message(exc)}", model_id=request.model_id) from exc

    # ------------------------------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------------------------------

    def start_run(self, request: RunRequest, *, wait: bool = False) -> RunRecord:
        """Validate synchronously, create the run (pending) and drive the graph.

        Raises ``ValidationFailed`` / ``LimitExceeded`` (and planner errors) before any run is created.
        ``wait=False`` returns the pending record at once; ``wait=True`` returns once the run is
        ``awaiting_review`` or ``failed``.
        """
        plan = resolve_plan(request)
        try:
            specs = self.planner.expand(plan, request.seed)
        except RiskbotError:
            raise
        except Exception as exc:
            raise RiskbotError(f"planning failed: {_message(exc)}") from exc
        if len(specs) > catalog.LIMITS["max_variations"]:
            raise LimitExceeded(f"variations: {len(specs)} exceeds the limit of {catalog.LIMITS['max_variations']}")
        now = utcnow()
        rec = RunRecord(
            run_id="run-" + uuid.uuid4().hex[:12], question=request.question, status=RunStatus.PENDING,
            created_at=now, updated_at=now,
            input_hash=run_input_hash(request.question.value, request.dataset, plan, request.seed),
            contract_version=CONTRACT_VERSION, n_variations=len(specs), dataset_name=request.dataset.name,
            synthetic=request.dataset.synthetic,
        )
        self.store.create_run(rec, request)
        self._audit(rec.run_id, "run_created", detail={"status": rec.status.value, "input_hash": rec.input_hash,
                                                       "n_variations": rec.n_variations, "use_llm": request.use_llm})
        initial: RunState = {"run_id": rec.run_id, "use_llm": request.use_llm, "plan": plan.model_dump(mode="json")}
        if wait:
            self._drive(rec.run_id, initial)
            return self.store.get_run(rec.run_id)
        t = threading.Thread(target=self._drive, args=(rec.run_id, initial), name=f"riskbot-{rec.run_id}",
                             daemon=True)
        self._threads[rec.run_id] = t
        t.start()
        return rec

    def join(self, run_id: str, timeout: float | None = None) -> RunRecord:
        """Wait for a background run's thread (test/CLI helper, not part of ``RunService``)."""
        t = self._threads.get(run_id)
        if t is not None:
            t.join(timeout)
        return self.store.get_run(run_id)

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        return self.store.list_runs(limit)

    def get_run(self, run_id: str) -> RunRecord:
        return self.store.get_run(run_id)

    def get_result(self, run_id: str) -> RunResult:
        rec = self.store.get_run(run_id)
        if rec.status in _NOT_FINISHED:
            raise Conflict(f"run {run_id} is {rec.status.value}; no result available", status=rec.status.value)
        return self.store.get_result(run_id).model_copy(update={"run": rec})

    def get_trace(self, trace_id: str) -> Trace:
        return self.store.get_trace(trace_id)

    def submit_review(self, run_id: str, review: ReviewSubmission) -> RunRecord:
        """Resume the paused graph with the review and return the record (approved / rejected).

        The edits are dry-run through the assessor first, so an invalid edit (unknown factor id) raises
        ``ValidationFailed`` and leaves the run awaiting review instead of breaking the graph.
        Two concurrent reviews of one run are serialised by the run lock; the second gets ``Conflict``.
        """
        def ensure_awaiting() -> None:
            rec = self.store.get_run(run_id)
            if rec.status != RunStatus.AWAITING_REVIEW:
                raise Conflict(f"run {run_id} is {rec.status.value}, not awaiting_review", status=rec.status.value)

        ensure_awaiting()  # fail fast without waiting for a graph that is still running
        with self._lock(run_id):  # then wait until the driver has checkpointed the interrupt
            ensure_awaiting()  # re-check: a concurrent review may have won
            self.assessor.apply_edits(self.store.get_result(run_id).assessment, review.factor_edits,
                                      review.reviewer, utcnow())
            snapshot = self.graph.get_state(self._config(run_id))
            if not snapshot.next:
                raise Conflict(f"run {run_id} has no paused graph in this checkpoint store")
            self._audit(run_id, "review_submitted", actor=review.reviewer,
                        detail={"decision": review.decision.value, "factor_edits": len(review.factor_edits)})
            try:
                self.graph.invoke(Command(resume=review.model_dump(mode="json")), self._config(run_id),
                                  durability="sync")
            except Exception as exc:
                self._fail(run_id, exc)
                raise RiskbotError(f"review of run {run_id} failed: {_message(exc)}") from exc
            return self.store.get_run(run_id)

    def get_report(self, run_id: str) -> Report:
        return self.reporter.build(self.get_result(run_id), self.store.get_signoff(run_id))

    def audit_log(self, run_id: str) -> list[AuditEvent]:
        self.store.get_run(run_id)  # NotFound for unknown runs
        return self.store.audit_log(run_id)

    def close(self) -> None:
        """Close the checkpoint database connection (idempotent)."""
        self._conn.close()

    def __enter__(self) -> OrchestratedRunService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
