"""Run lifecycle on fakes: every question, sync and async, concurrency, failures and the audit trail."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from riskbot.contract import CONTRACT_VERSION, catalog, fakes
from riskbot.contract.errors import Conflict
from riskbot.contract.hashing import run_input_hash
from riskbot.contract.types import (
    QuestionId,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunStatus,
)
from riskbot.orchestration.tests.helpers import make_service, poll, registry_with

APPROVE = ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="ana", comment="ok")


def _request(q: QuestionId, **kw) -> RunRequest:
    return RunRequest(question=q, dataset=fakes.fake_dataset(q), **kw)


@pytest.mark.parametrize("q", list(QuestionId))
def test_full_lifecycle_wait(svc, q):
    req = _request(q)
    rec = svc.start_run(req, wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW and rec.error is None
    assert re.fullmatch(r"run-[0-9a-f]{12}", rec.run_id)
    assert rec.contract_version == CONTRACT_VERSION
    plan = catalog.DEFAULT_PLANS[q]
    assert rec.input_hash == run_input_hash(q.value, req.dataset, plan, req.seed)
    assert rec.n_variations == len(fakes.FakePlanner().expand(plan, req.seed))
    assert rec.created_at.tzinfo is not None and rec.updated_at >= rec.created_at
    assert rec.dataset_name == req.dataset.name and rec.synthetic is True

    result = svc.get_result(rec.run_id)
    assert result.run.status == RunStatus.AWAITING_REVIEW
    assert result.plan == plan
    assert [v.spec.variation_id for v in result.variations] == [
        s.variation_id for s in fakes.FakePlanner().expand(plan, req.seed)]  # order preserved
    assert all(v.output is not None for v in result.variations)
    assert result.comparison.question == q and result.comparison.metric_ranges
    assert result.assessment.question == q

    report_before = svc.get_report(rec.run_id)
    assert report_before.signoff is None

    trace_id = result.variations[0].output.traces[0].trace_id
    assert svc.get_trace(trace_id).trace_id == trace_id

    done = svc.submit_review(rec.run_id, APPROVE)
    assert done.status == RunStatus.APPROVED
    report = svc.get_report(rec.run_id)
    assert report.signoff is not None and report.signoff.decision == ReviewDecision.APPROVE
    assert report.run.status == RunStatus.APPROVED


@pytest.mark.parametrize("q", list(QuestionId))
def test_full_lifecycle_background_polling(svc, q):
    rec = svc.start_run(_request(q), wait=False)
    assert rec.status in (RunStatus.PENDING, RunStatus.RUNNING)
    final = poll(svc, rec.run_id)
    assert final.status == RunStatus.AWAITING_REVIEW
    assert svc.submit_review(rec.run_id, APPROVE).status == RunStatus.APPROVED
    assert svc.get_report(rec.run_id).signoff.reviewer == "ana"


def test_concurrent_runs_background_and_blocking(svc):
    background = [svc.start_run(_request(q, seed=i), wait=False) for i in range(3) for q in QuestionId]
    with ThreadPoolExecutor(max_workers=4) as pool:
        blocking = list(pool.map(lambda q: svc.start_run(_request(q), wait=True), list(QuestionId) * 2))
    assert all(r.status == RunStatus.AWAITING_REVIEW for r in blocking)
    for r in background:
        assert poll(svc, r.run_id).status == RunStatus.AWAITING_REVIEW
    ids = [r.run_id for r in background + blocking]
    assert len(set(ids)) == len(ids)
    with ThreadPoolExecutor(max_workers=4) as pool:
        reviewed = list(pool.map(lambda rid: svc.submit_review(rid, APPROVE), ids))
    assert {r.status for r in reviewed} == {RunStatus.APPROVED}
    # Each run kept its own result.
    for r in background + blocking:
        assert svc.get_result(r.run_id).run.run_id == r.run_id
    assert len(svc.list_runs(limit=100)) == len(ids)


def test_list_runs_newest_first(svc):
    a = svc.start_run(_request(QuestionId.Q1), wait=True)
    b = svc.start_run(_request(QuestionId.Q2), wait=True)
    assert [r.run_id for r in svc.list_runs()] == [b.run_id, a.run_id]
    assert [r.run_id for r in svc.list_runs(limit=1)] == [b.run_id]


def test_all_grid_variations_fail_marks_run_failed():
    svc = make_service(registry=registry_with("q1.var"))
    rec = svc.start_run(_request(QuestionId.Q1), wait=True)
    assert rec.status == RunStatus.FAILED
    assert "grid variations failed" in rec.error and "RuntimeError" in rec.error
    with pytest.raises(Conflict):
        svc.get_result(rec.run_id)
    with pytest.raises(Conflict):
        svc.get_report(rec.run_id)
    with pytest.raises(Conflict):
        svc.submit_review(rec.run_id, APPROVE)
    last = svc.audit_log(rec.run_id)[-1]
    assert last.event == "status_changed" and last.detail["to"] == "failed" and last.detail["error"] == rec.error


def test_all_grid_variations_fail_in_background():
    svc = make_service(registry=registry_with("q3.transition"))
    rec = svc.start_run(_request(QuestionId.Q3), wait=False)
    assert poll(svc, rec.run_id).status == RunStatus.FAILED


def test_partial_failure_still_awaits_review():
    svc = make_service(registry=registry_with("q1.var", when=lambda p: p.get("method") == "evt"))
    rec = svc.start_run(_request(QuestionId.Q1), wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW
    result = svc.get_result(rec.run_id)
    failed = [v for v in result.variations if v.error]
    assert failed and all(v.spec.params["method"] == "evt" and v.error.startswith("RuntimeError") for v in failed)
    assert any(v.output for v in result.variations)
    events = [e for e in svc.audit_log(rec.run_id) if e.event == "variations_failed"]
    assert events and events[0].detail["failed"] == len(failed)


def test_failing_extra_run_does_not_fail_the_run():
    svc = make_service(registry=registry_with("q2.data_quality"))
    rec = svc.start_run(_request(QuestionId.Q2), wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW


class _GatedModel(fakes.FakeModel):
    """Blocks until ``gate`` is set, so tests can observe a run while it is running."""

    def __init__(self, spec, gate: threading.Event) -> None:
        super().__init__(spec)
        self.gate = gate

    def run(self, dataset, params, seed):
        assert self.gate.wait(10)
        return super().run(dataset, params, seed)


def test_conflicts_while_running():
    gate = threading.Event()
    models = [_GatedModel(s, gate) if s.model_id == "q1.var" else fakes.FakeModel(s)
              for s in catalog.MODEL_SPECS.values()]
    svc = make_service(registry=fakes.FakeRegistry(models))
    rec = svc.start_run(_request(QuestionId.Q1), wait=False)
    poll(svc, rec.run_id, until=(RunStatus.RUNNING,))
    with pytest.raises(Conflict):
        svc.get_result(rec.run_id)
    with pytest.raises(Conflict):
        svc.get_report(rec.run_id)
    with pytest.raises(Conflict):
        svc.submit_review(rec.run_id, APPROVE)  # fails fast, does not wait for the graph
    gate.set()
    assert poll(svc, rec.run_id).status == RunStatus.AWAITING_REVIEW


def test_audit_log_ordering(svc):
    rec = svc.start_run(_request(QuestionId.Q2), wait=True)
    svc.submit_review(rec.run_id, ReviewSubmission(
        decision=ReviewDecision.REJECT, reviewer="bo", comment="needs work",
        factor_edits=[{"factor_id": "fake_factor", "likelihood": 5, "impact": 4, "reason": "deposit flight"}]))
    log = svc.audit_log(rec.run_id)
    assert [(e.event, e.actor) for e in log] == [
        ("run_created", "system"),
        ("status_changed", "system"),  # pending -> running
        ("status_changed", "system"),  # running -> awaiting_review
        ("review_submitted", "bo"),
        ("factor_edited", "bo"),  # likelihood
        ("factor_edited", "bo"),  # impact
        ("signed_off", "bo"),
        ("report_built", "system"),
        ("status_changed", "bo"),  # awaiting_review -> rejected (written last)
    ]
    transitions = [(e.detail["from"], e.detail["to"]) for e in log if e.event == "status_changed"]
    assert transitions == [("pending", "running"), ("running", "awaiting_review"), ("awaiting_review", "rejected")]
    assert log[0].detail["status"] == "pending"
    assert all(a.at <= b.at for a, b in zip(log, log[1:]))
    assert all(e.at.tzinfo is not None and e.run_id == rec.run_id for e in log)
