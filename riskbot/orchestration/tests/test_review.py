"""Review, sign-off, report and checkpoint resume across service instances."""

from __future__ import annotations

import threading

import pytest

from riskbot.contract import fakes
from riskbot.contract.errors import Conflict, RiskbotError, ValidationFailed
from riskbot.contract.types import (
    FactorEdit,
    FactorSource,
    QuestionId,
    Report,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunStatus,
)
from riskbot.orchestration.tests.helpers import NumberFlaggingVerifier, make_service


def _start(svc, q=QuestionId.Q1):
    return svc.start_run(RunRequest(question=q, dataset=fakes.fake_dataset(q)), wait=True)


@pytest.mark.parametrize("decision,status", [(ReviewDecision.APPROVE, RunStatus.APPROVED),
                                             (ReviewDecision.REJECT, RunStatus.REJECTED)])
def test_review_with_factor_edits(svc, decision, status):
    rec = _start(svc)
    review = ReviewSubmission(decision=decision, reviewer="carla", comment="checked",
                              factor_edits=[FactorEdit(factor_id="fake_factor", likelihood=5, control="weak",
                                                       rationale="Analyst view.", reason="short book is large")])
    out = svc.submit_review(rec.run_id, review)
    assert out.status == status and out.updated_at >= rec.updated_at

    result = svc.get_result(rec.run_id)
    assert result.run.status == status
    factor = result.assessment.factors[0]
    assert factor.source == FactorSource.ANALYST and factor.likelihood == 5 and factor.rationale == "Analyst view."
    assert {(o.field, o.by) for o in result.assessment.overrides} == {
        ("likelihood", "carla"), ("control", "carla"), ("rationale", "carla")}

    signoff = svc.store.get_signoff(rec.run_id)
    assert signoff.reviewer == "carla" and signoff.decision == decision and signoff.comment == "checked"
    assert signoff.at.tzinfo is not None

    report = svc.get_report(rec.run_id)
    assert report.signoff == signoff and report.run.status == status
    assert report.assessment.overrides == result.assessment.overrides
    edits = [e for e in svc.audit_log(rec.run_id) if e.event == "factor_edited"]
    assert {e.detail["field"] for e in edits} == {"likelihood", "control", "rationale"}
    assert all(e.detail["reason"] == "short book is large" for e in edits)


def test_double_review_conflict(svc):
    rec = _start(svc)
    review = ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="dan")
    svc.submit_review(rec.run_id, review)
    with pytest.raises(Conflict):
        svc.submit_review(rec.run_id, review)


def test_concurrent_double_review_only_one_wins(svc):
    rec = _start(svc)
    review = ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="eve")
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        try:
            svc.submit_review(rec.run_id, review)
            outcomes.append("ok")
        except Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    assert len([e for e in svc.audit_log(rec.run_id) if e.event == "signed_off"]) == 1


def test_invalid_edit_keeps_run_awaiting_review(svc):
    rec = _start(svc)
    bad = ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="fay",
                           factor_edits=[FactorEdit(factor_id="nope", impact=2, reason="x")])
    with pytest.raises(ValidationFailed):
        svc.submit_review(rec.run_id, bad)
    assert svc.get_run(rec.run_id).status == RunStatus.AWAITING_REVIEW
    good = ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="fay")
    assert svc.submit_review(rec.run_id, good).status == RunStatus.APPROVED


def test_unknown_run_raises_not_found(svc):
    from riskbot.contract.errors import NotFound

    for call in (svc.get_run, svc.get_result, svc.get_report, svc.audit_log):
        with pytest.raises(NotFound):
            call("run-000000000000")
    with pytest.raises(NotFound):
        svc.submit_review("run-000000000000", ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="x"))


class _NumberedReporter(fakes.FakeReporter):
    def build(self, result, signoff) -> Report:
        rep = super().build(result, signoff)
        return rep.model_copy(update={"headline": ["Spread is 0.5.", "VaR could be 9.99%."]})


def test_report_headline_is_verified_and_findings_appended():
    svc = make_service(verifier=NumberFlaggingVerifier(allowed={0.5}), reporter=_NumberedReporter())
    rec = _start(svc)
    assert svc.get_result(rec.run_id).verifier_findings == []
    svc.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="gil"))
    findings = svc.get_result(rec.run_id).verifier_findings
    assert [(f.location, f.value, f.matched) for f in findings] == [
        ("report:headline/0", 0.5, True), ("report:headline/1", 9.99, False)]
    built = [e for e in svc.audit_log(rec.run_id) if e.event == "report_built"][0]
    assert built.detail == {"headline_sentences": 2, "unmatched_numbers": 1}


def test_checkpoint_resume_in_new_service_instance(tmp_path):
    path = str(tmp_path / "checkpoints.sqlite")
    store = fakes.FakeStore()
    first = make_service(store=store, checkpoint_path=path)
    rec = _start(first, QuestionId.Q3)
    assert rec.status == RunStatus.AWAITING_REVIEW
    first.close()
    del first

    second = make_service(store=store, checkpoint_path=path)
    review = ReviewSubmission(decision=ReviewDecision.REJECT, reviewer="hal", comment="data too thin",
                              factor_edits=[FactorEdit(factor_id="fake_factor", impact=5, reason="coverage")])
    out = second.submit_review(rec.run_id, review)
    assert out.status == RunStatus.REJECTED
    report = second.get_report(rec.run_id)
    assert report.signoff.reviewer == "hal" and report.assessment.factors[0].impact == 5
    assert [e.event for e in second.audit_log(rec.run_id)][-2:] == ["report_built", "status_changed"]
    second.close()


def test_resume_without_checkpoint_is_a_conflict(tmp_path):
    store = fakes.FakeStore()
    first = make_service(store=store, checkpoint_path=str(tmp_path / "a.sqlite"))
    rec = _start(first)
    other = make_service(store=store, checkpoint_path=str(tmp_path / "b.sqlite"))
    with pytest.raises(Conflict, match="no paused graph"):
        other.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="ian"))
    assert store.get_run(rec.run_id).status == RunStatus.AWAITING_REVIEW


class _BrokenReporter(fakes.FakeReporter):
    def build(self, result, signoff):
        if signoff is not None:
            raise RuntimeError("template missing")
        return super().build(result, signoff)


def test_unexpected_error_during_review_fails_run():
    svc = make_service(reporter=_BrokenReporter())
    rec = _start(svc)
    with pytest.raises(RiskbotError, match="template missing"):
        svc.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="jo"))
    failed = svc.get_run(rec.run_id)
    assert failed.status == RunStatus.FAILED and "RuntimeError: template missing" in failed.error
