"""The LangGraph state machine behind one run.

::

    START -> validate -> plan -> execute -> check_outputs -> compare -> assess
          -> [draft_rationales if use_llm and a drafter is configured] -> verify_text
          -> await_review (interrupt)  ... resumed by Command(resume=ReviewSubmission dict) ...
          -> apply_edits -> signoff -> report -> END

State design
------------
The state is plain JSON (``model_dump(mode="json")`` dicts), so the ``SqliteSaver`` checkpointer can
store it with the default serializer and a different process can resume it. The request (which holds
the possibly large dataset) is *not* copied into the state: nodes load it from the ``RunStore`` by
``run_id``. The run's published artefacts (``RunRecord``, ``RunResult``, ``SignOff``, audit log) live
in the ``RunStore``; the checkpoint holds only what the graph needs to continue.

Failure semantics
-----------------
A node signals an unrecoverable error by raising. The driver in ``service.py`` catches it and moves
the run to ``failed`` with the message. Individual variation failures are *not* errors: the executor
captures them in ``VariationResult.error``. Only "zero successful grid variations" fails the run.
"""

from __future__ import annotations

import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from riskbot.contract import catalog, ports
from riskbot.contract.errors import RiskbotError
from riskbot.contract.types import (
    Comparison,
    FactorSource,
    QualitativeAssessment,
    QuestionPlan,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunResult,
    RunStatus,
    SignOff,
    VariationResult,
    VariationSpec,
    VerifierFinding,
)

from .validation import check_dataset_kind, check_limits


class RunState(TypedDict, total=False):
    """Checkpointed state of one run (thread_id = run_id). Every value is JSON-serialisable.

    Keys
    ----
    run_id             the run (also the LangGraph thread id)
    use_llm            request.use_llm, copied so routing does not need the store
    plan               resolved ``QuestionPlan`` (request.plan or the catalogue default)
    specs              ``VariationSpec`` list from the planner (grid first, then extras)
    variations         ``VariationResult`` list, same order as ``specs``
    output_findings    ``VerifierFinding`` list from ``verifier.check_outputs``
    comparison         ``Comparison``
    assessment         ``QualitativeAssessment`` (rule pre-fill, then accepted drafts, then edits)
    drafts             factor_id -> drafted rationale (empty when no LLM)
    verifier_findings  all findings published with the result (outputs + drafts)
    review             the ``ReviewSubmission`` passed to ``Command(resume=...)``
    signoff            the stored ``SignOff``
    """

    run_id: str
    use_llm: bool
    plan: dict[str, Any]
    specs: list[dict[str, Any]]
    variations: list[dict[str, Any]]
    output_findings: list[dict[str, Any]]
    comparison: dict[str, Any]
    assessment: dict[str, Any]
    drafts: dict[str, str]
    verifier_findings: list[dict[str, Any]]
    review: dict[str, Any]
    signoff: dict[str, Any]


def utcnow() -> dt.datetime:
    """Timezone-aware UTC now (contract convention: store datetimes in UTC)."""
    return dt.datetime.now(dt.timezone.utc)


def _dump(items: list[Any]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json") for i in items]


@dataclass
class GraphDeps:
    """Everything the nodes need. ``transition`` and ``audit`` are provided by the service so the
    status/audit rules live in one place."""

    store: ports.RunStore
    planner: ports.VariationPlanner
    executor: ports.VariationExecutor
    comparator: ports.Comparator
    verifier: ports.NumberVerifier
    reporter: ports.Reporter
    assessor: ports.Assessor
    drafter: ports.RationaleDrafter | None
    transition: Callable[..., Any]  # (run_id, status, *, actor="system", error=None, detail=None) -> RunRecord
    audit: Callable[..., None]  # (run_id, event, *, actor="system", detail=None) -> None
    max_workers: int = max(1, min(4, os.cpu_count() or 1))


class RunNodes:
    """Node implementations. Each takes the state and returns a partial update."""

    def __init__(self, deps: GraphDeps) -> None:
        self.d = deps

    # -- helpers --------------------------------------------------------------------------------

    def _request(self, state: RunState) -> RunRequest:
        return self.d.store.get_request(state["run_id"])

    @staticmethod
    def _results(state: RunState) -> list[VariationResult]:
        return [VariationResult.model_validate(v) for v in state.get("variations", [])]

    # -- nodes ----------------------------------------------------------------------------------

    def validate(self, state: RunState) -> RunState:
        """pending -> running; re-check the dataset defensively (start_run already validated it)."""
        req = self._request(state)
        check_dataset_kind(req.dataset, catalog.QUESTIONS[req.question].dataset_kind, f"question {req.question.value}")
        check_limits(req.dataset)
        self.d.transition(state["run_id"], RunStatus.RUNNING)
        return {}

    def plan(self, state: RunState) -> RunState:
        """Expand the plan into variation specs (deterministic; identical to the expansion in start_run)."""
        plan = QuestionPlan.model_validate(state["plan"])
        specs = self.d.planner.expand(plan, self._request(state).seed)
        return {"specs": _dump(specs)}

    def execute(self, state: RunState) -> RunState:
        """Run every variation on a bounded thread pool, preserving order. Fails the run only if no grid
        variation succeeded."""
        dataset = self._request(state).dataset
        specs = [VariationSpec.model_validate(s) for s in state["specs"]]

        def run_one(spec: VariationSpec) -> VariationResult:
            try:
                return self.d.executor.execute(spec, dataset)
            except Exception as exc:  # the executor should never raise; keep the run alive if it does
                return VariationResult(spec=spec, error=f"{type(exc).__name__}: {exc}", duration_ms=0.0)

        with ThreadPoolExecutor(max_workers=self.d.max_workers, thread_name_prefix="riskbot-var") as pool:
            results = list(pool.map(run_one, specs))
        grid = [r for r in results if r.spec.role == "grid"]
        ok = [r for r in grid if r.output is not None and r.error is None]
        if not ok:
            first = next((r.error for r in grid if r.error), "no grid variations planned")
            raise RiskbotError(f"all {len(grid)} grid variations failed; first error: {first}")
        failed = len(results) - sum(1 for r in results if r.output is not None and r.error is None)
        if failed:
            self.d.audit(state["run_id"], "variations_failed", detail={"failed": failed, "total": len(results)})
        return {"variations": _dump(results)}

    def check_outputs(self, state: RunState) -> RunState:
        """Every metric must equal its trace step (``NumberVerifier.check_outputs``); findings are kept."""
        findings = self.d.verifier.check_outputs(self._results(state))
        return {"output_findings": _dump(findings)}

    def compare(self, state: RunState) -> RunState:
        plan = QuestionPlan.model_validate(state["plan"])
        comparison = self.d.comparator.compare(plan, self._results(state))
        return {"comparison": comparison.model_dump(mode="json")}

    def assess(self, state: RunState) -> RunState:
        req = self._request(state)
        assessment = self.d.assessor.assess(req.question, req.dataset, self._results(state),
                                            Comparison.model_validate(state["comparison"]))
        return {"assessment": assessment.model_dump(mode="json"), "drafts": {}}

    def draft_rationales(self, state: RunState) -> RunState:
        """Ask the drafter for rationales. A drafter failure never fails the run: rule rationales stay."""
        assert self.d.drafter is not None
        assessment = QualitativeAssessment.model_validate(state["assessment"])
        try:
            drafts = self.d.drafter.draft(assessment, self._results(state))
        except Exception as exc:
            self.d.audit(state["run_id"], "llm_draft_failed", detail={"error": f"{type(exc).__name__}: {exc}"})
            drafts = {}
        return {"drafts": {str(k): str(v) for k, v in (drafts or {}).items()}}

    def verify_text(self, state: RunState) -> RunState:
        """Verify each drafted rationale against the run's metrics. A draft with any unmatched number is
        rejected (rule rationale kept, findings recorded); accepted drafts get ``source=llm_draft``."""
        results = self._results(state)
        assessment = QualitativeAssessment.model_validate(state["assessment"])
        findings = [VerifierFinding.model_validate(f) for f in state.get("output_findings", [])]
        drafts = state.get("drafts") or {}
        factors = {f.factor_id: f for f in assessment.factors}
        for fid, text in drafts.items():
            location = f"factor:{fid}/rationale"
            if fid not in factors:
                findings.append(VerifierFinding(location=location, text=text, value=None, matched=False,
                                                message=f"draft for unknown factor {fid!r} ignored"))
                continue
            got = self.d.verifier.verify_text(location, text, results)
            bad = [f for f in got if not f.matched]
            findings.extend(got)
            if bad:
                self.d.audit(state["run_id"], "llm_draft_rejected",
                             detail={"factor_id": fid, "unmatched": [f.text for f in bad]})
            else:
                factors[fid] = factors[fid].model_copy(update={"rationale": text, "source": FactorSource.LLM_DRAFT})
                self.d.audit(state["run_id"], "llm_draft_accepted", detail={"factor_id": fid})
        assessment = assessment.model_copy(update={"factors": [factors[f.factor_id] for f in assessment.factors]})
        return {"assessment": assessment.model_dump(mode="json"), "verifier_findings": _dump(findings)}

    def await_review(self, state: RunState) -> RunState:
        """Publish the result, move to awaiting_review and pause for a human.

        LangGraph re-executes this node from the top when the run is resumed, so publishing is guarded:
        it happens only while the stored status is still ``running``.
        """
        run_id = state["run_id"]
        if self.d.store.get_run(run_id).status == RunStatus.RUNNING:
            rec = self.d.store.get_run(run_id)
            self.d.store.save_result(RunResult(
                run=rec.model_copy(update={"status": RunStatus.AWAITING_REVIEW}),
                plan=QuestionPlan.model_validate(state["plan"]),
                variations=self._results(state),
                comparison=Comparison.model_validate(state["comparison"]),
                assessment=QualitativeAssessment.model_validate(state["assessment"]),
                verifier_findings=[VerifierFinding.model_validate(f) for f in state.get("verifier_findings", [])],
            ))
            self.d.transition(run_id, RunStatus.AWAITING_REVIEW)
        review = interrupt({"run_id": run_id, "awaiting": "review"})
        return {"review": ReviewSubmission.model_validate(review).model_dump(mode="json")}

    def apply_edits(self, state: RunState) -> RunState:
        """Apply the reviewer's factor edits via the assessor; one audit event per recorded override."""
        review = ReviewSubmission.model_validate(state["review"])
        before = QualitativeAssessment.model_validate(state["assessment"])
        after = self.d.assessor.apply_edits(before, review.factor_edits, review.reviewer, utcnow())
        for o in after.overrides[len(before.overrides):]:
            self.d.audit(state["run_id"], "factor_edited", actor=review.reviewer,
                         detail=o.model_dump(mode="json", exclude={"by", "at"}))
        return {"assessment": after.model_dump(mode="json")}

    def signoff(self, state: RunState) -> RunState:
        """Store the sign-off and the edited assessment (status stays awaiting_review until the report)."""
        run_id = state["run_id"]
        review = ReviewSubmission.model_validate(state["review"])
        so = SignOff(reviewer=review.reviewer, decision=review.decision, comment=review.comment, at=utcnow())
        self.d.store.save_signoff(run_id, so)
        result = self.d.store.get_result(run_id)
        self.d.store.save_result(result.model_copy(
            update={"assessment": QualitativeAssessment.model_validate(state["assessment"])}))
        self.d.audit(run_id, "signed_off", actor=review.reviewer,
                     detail={"decision": review.decision.value, "comment": review.comment})
        return {"signoff": so.model_dump(mode="json")}

    def report(self, state: RunState) -> RunState:
        """Build the report, verify every headline sentence, then awaiting_review -> approved | rejected.

        The final status is written last, so a run is only approved/rejected once its report could be
        built; headline findings are appended to the stored result.
        """
        run_id = state["run_id"]
        review = ReviewSubmission.model_validate(state["review"])
        status = RunStatus.APPROVED if review.decision == ReviewDecision.APPROVE else RunStatus.REJECTED
        final = self.d.store.get_run(run_id).model_copy(update={"status": status})
        result = self.d.store.get_result(run_id).model_copy(update={"run": final})
        report = self.d.reporter.build(result, SignOff.model_validate(state["signoff"]))
        findings: list[VerifierFinding] = []
        for i, sentence in enumerate(report.headline):
            findings += self.d.verifier.verify_text(f"report:headline/{i}", sentence, result.variations)
        self.d.audit(run_id, "report_built", detail={
            "headline_sentences": len(report.headline),
            "unmatched_numbers": sum(1 for f in findings if not f.matched)})
        self.d.store.save_result(result.model_copy(
            update={"verifier_findings": [*result.verifier_findings, *findings]}))
        self.d.transition(run_id, status, actor=review.reviewer)
        return {}


def build_graph(deps: GraphDeps, checkpointer: Any) -> Any:
    """Compile the run graph with ``checkpointer`` (a ``SqliteSaver``)."""
    n = RunNodes(deps)
    g = StateGraph(RunState)
    for name in ("validate", "plan", "execute", "check_outputs", "compare", "assess", "draft_rationales",
                 "verify_text", "await_review", "apply_edits", "signoff", "report"):
        g.add_node(name, getattr(n, name))

    def route_after_assess(state: RunState) -> str:
        return "draft_rationales" if state.get("use_llm") and deps.drafter is not None else "verify_text"

    g.add_edge(START, "validate")
    g.add_edge("validate", "plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "check_outputs")
    g.add_edge("check_outputs", "compare")
    g.add_edge("compare", "assess")
    g.add_conditional_edges("assess", route_after_assess, ["draft_rationales", "verify_text"])
    g.add_edge("draft_rationales", "verify_text")
    g.add_edge("verify_text", "await_review")
    g.add_edge("await_review", "apply_edits")
    g.add_edge("apply_edits", "signoff")
    g.add_edge("signoff", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["GraphDeps", "RunNodes", "RunState", "build_graph", "utcnow"]
