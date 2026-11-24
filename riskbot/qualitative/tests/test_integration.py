"""End to end inside contract.fakes.FakeRunService, and documentation coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from riskbot.contract import rules
from riskbot.contract.fakes import FakeRunService
from riskbot.contract.types import (
    FactorEdit,
    FactorSource,
    QuestionId,
    Rating,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunResult,
    RunStatus,
)
from riskbot.qualitative import CONTRACT_FACTOR_IDS, RUBRICS, assessor


@pytest.mark.parametrize("q", list(QuestionId))
def test_runs_inside_fake_run_service(q):
    svc = FakeRunService()
    svc.assessor = assessor()
    rec = svc.start_run(RunRequest(question=q, dataset=svc.sample_dataset(q)), wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW
    res = svc.get_result(rec.run_id)
    assert RunResult.model_validate_json(res.model_dump_json()) == res
    assert [f.factor_id for f in res.assessment.factors] == list(CONTRACT_FACTOR_IDS[q])
    assert any(f.source == FactorSource.RULE for f in res.assessment.factors)
    fid = res.assessment.factors[0].factor_id
    svc.submit_review(rec.run_id, ReviewSubmission(
        decision=ReviewDecision.APPROVE, reviewer="analyst",
        factor_edits=[FactorEdit(factor_id=fid, likelihood=5, impact=5, reason="test")]))
    rep = svc.get_report(rec.run_id)
    assert rep.assessment.factors[0].inherent == Rating.CRITICAL
    assert rep.assessment.factors[0].source == FactorSource.ANALYST
    assert rep.assessment.overall == rules.overall_rating([f.residual for f in rep.assessment.factors])
    f0 = res.assessment.factors[0]
    changed = {k for k, old in (("likelihood", f0.likelihood), ("impact", f0.impact)) if old != 5}
    assert {o.field for o in rep.assessment.overrides} == changed  # only real changes are logged


def test_readme_documents_every_factor():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    for q, rows in RUBRICS.items():
        for fd in rows:
            assert f"`{fd.factor_id}`" in text, fd.factor_id
    assert "judgment" in text.lower()
