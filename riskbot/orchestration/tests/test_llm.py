"""LLM drafting path: drafts are verified; unverifiable numbers are rejected per factor."""

from __future__ import annotations

from riskbot.contract import fakes
from riskbot.contract.types import FactorSource, QuestionId, RunRequest, RunStatus
from riskbot.orchestration import ScriptedDrafter
from riskbot.orchestration.tests.helpers import NumberFlaggingVerifier, make_service

RULE_TEXT = "Placeholder rationale."  # FakeAssessor's rule rationale


def _run(svc, use_llm=True, q=QuestionId.Q1):
    rec = svc.start_run(RunRequest(question=q, dataset=fakes.fake_dataset(q), use_llm=use_llm), wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW
    return svc.get_result(rec.run_id), rec


def test_clean_draft_is_accepted():
    drafter = ScriptedDrafter({"fake_factor": "Method spread of 0.5 suggests moderate model risk."})
    svc = make_service(drafter=drafter, verifier=NumberFlaggingVerifier(allowed={0.5}))
    result, rec = _run(svc)
    factor = result.assessment.factors[0]
    assert factor.source == FactorSource.LLM_DRAFT
    assert factor.rationale.startswith("Method spread of 0.5")
    assert [f.matched for f in result.verifier_findings] == [True]
    assert result.verifier_findings[0].location == "factor:fake_factor/rationale"
    assert drafter.calls == [["fake_factor"]]
    assert any(e.event == "llm_draft_accepted" for e in svc.audit_log(rec.run_id))


def test_draft_with_invented_number_is_rejected():
    drafter = ScriptedDrafter({"fake_factor": "Losses could reach 42.7% in a bad week."})
    svc = make_service(drafter=drafter, verifier=NumberFlaggingVerifier(allowed={0.5}))
    result, rec = _run(svc)
    factor = result.assessment.factors[0]
    assert factor.source == FactorSource.RULE and factor.rationale == RULE_TEXT
    bad = [f for f in result.verifier_findings if not f.matched]
    assert len(bad) == 1
    assert bad[0].location == "factor:fake_factor/rationale" and bad[0].value == 42.7
    rejected = [e for e in svc.audit_log(rec.run_id) if e.event == "llm_draft_rejected"]
    assert rejected and rejected[0].detail == {"factor_id": "fake_factor", "unmatched": ["42.7"]}


def test_draft_for_unknown_factor_is_recorded_and_ignored():
    class Loose(ScriptedDrafter):
        def draft(self, assessment, results):
            return dict(self.responses)

    svc = make_service(drafter=Loose({"ghost": "No numbers here."}))
    result, _ = _run(svc)
    assert result.assessment.factors[0].rationale == RULE_TEXT
    assert [(f.location, f.matched) for f in result.verifier_findings] == [("factor:ghost/rationale", False)]


def test_drafter_not_called_without_use_llm():
    drafter = ScriptedDrafter({"fake_factor": "Fine."})
    svc = make_service(drafter=drafter)
    result, _ = _run(svc, use_llm=False)
    assert drafter.calls == [] and result.assessment.factors[0].source == FactorSource.RULE


def test_use_llm_without_drafter_uses_rules():
    svc = make_service(drafter=None)
    result, _ = _run(svc, use_llm=True)
    assert result.assessment.factors[0].source == FactorSource.RULE


def test_failing_drafter_does_not_fail_the_run():
    class Broken:
        def draft(self, assessment, results):
            raise TimeoutError("model API timed out")

    svc = make_service(drafter=Broken())
    result, rec = _run(svc)
    assert result.assessment.factors[0].rationale == RULE_TEXT
    failed = [e for e in svc.audit_log(rec.run_id) if e.event == "llm_draft_failed"]
    assert failed and "TimeoutError" in failed[0].detail["error"]
