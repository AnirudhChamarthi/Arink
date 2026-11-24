"""End-to-end tests of the real components wired by the composition root."""

import asyncio

import pytest

from riskbot.app import build_registry, build_service
from riskbot.contract import catalog
from riskbot.contract.types import (
    CalcRequest,
    QuestionId,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunStatus,
)

RUBRIC_FACTORS = {
    QuestionId.Q1: {"method_spread", "backtest_performance", "history_length", "data_quality", "concentration",
                    "short_exposure", "normality_reliance"},
    QuestionId.Q2: {"uninsured_deposits", "deposit_concentration", "duration_gap", "hedging", "htm_reliance",
                    "wholesale_dependence", "risk_governance", "credit_concentration"},
    QuestionId.Q3: {"emissions_coverage", "estimated_emissions", "scope3_coverage", "stale_data", "controversies",
                    "exclusion_breaches", "high_emitting_concentration", "scenario_dispersion"},
}


@pytest.fixture(scope="module")
def service():
    return build_service()


@pytest.fixture(scope="module")
def completed(service):
    """One full run per question on the sample data (shared by the tests below)."""
    out = {}
    for q in QuestionId:
        rec = service.start_run(RunRequest(question=q, dataset=service.sample_dataset(q)), wait=True)
        out[q] = rec
    return out


def test_every_catalogued_model_is_registered():
    assert {s.model_id for s in build_registry().specs()} == set(catalog.MODEL_SPECS)


@pytest.mark.parametrize("q", list(QuestionId))
def test_run_reaches_review_with_all_variations_succeeding(service, completed, q):
    rec = completed[q]
    assert rec.status == RunStatus.AWAITING_REVIEW, rec.error
    result = service.get_result(rec.run_id)
    errors = [(v.spec.model_id, v.spec.params, v.error) for v in result.variations if v.error]
    assert not errors, errors
    assert rec.synthetic and result.comparison.metric_ranges


@pytest.mark.parametrize("q", list(QuestionId))
def test_every_metric_matches_its_trace_and_traces_are_retrievable(service, completed, q):
    result = service.get_result(completed[q].run_id)
    assert not [f for f in result.verifier_findings if not f.matched]
    first = next(m for v in result.variations if v.output for m in v.output.metrics.values())
    trace = service.get_trace(first.trace_id)
    assert any(s.id == first.trace_step and s.value == pytest.approx(first.value) for s in trace.steps)


@pytest.mark.parametrize("q", list(QuestionId))
def test_assessment_covers_the_rubric(service, completed, q):
    result = service.get_result(completed[q].run_id)
    assert {f.factor_id for f in result.assessment.factors} == RUBRIC_FACTORS[q]


def test_designed_behaviour_of_sample_data(service, completed):
    q1 = service.get_result(completed[QuestionId.Q1].run_id)
    assert q1.comparison.method_spread.get("var", 0) > 1.0
    q2 = service.get_result(completed[QuestionId.Q2].run_id)
    verdicts = q2.comparison.label_counts["verdict"]
    assert verdicts.get("pass", 0) > 0 and verdicts.get("fail", 0) > 0  # some scenarios pass, some fail
    assert any(b.found for b in q2.comparison.break_evens)
    q3 = service.get_result(completed[QuestionId.Q3].run_id)
    r = q3.comparison.metric_ranges["loss_pct"]
    assert r.max > r.min >= 0


@pytest.mark.parametrize("q", list(QuestionId))
def test_review_and_report_with_verified_headline(service, completed, q):
    from riskbot import services

    rec = completed[q]
    result = service.get_result(rec.run_id)
    factor = result.assessment.factors[0]
    new_impact = 1 if factor.impact != 1 else 5  # must differ, or no override is logged (by design)
    from riskbot.contract.types import FactorEdit

    approved = service.submit_review(rec.run_id, ReviewSubmission(
        decision=ReviewDecision.APPROVE, reviewer="integration-test",
        factor_edits=[FactorEdit(factor_id=factor.factor_id, impact=new_impact, reason="integration check")]))
    assert approved.status == RunStatus.APPROVED
    report = service.get_report(rec.run_id)
    assert report.signoff and report.assessment.overrides
    findings = services.verifier().verify_text("headline", " ".join(report.headline), result.variations)
    assert all(f.matched for f in findings), [f for f in findings if not f.matched]
    events = [e.event for e in service.audit_log(rec.run_id)]
    assert events and len(events) >= 4


def test_calc_and_validate_on_real_models(service):
    ds = service.sample_dataset(QuestionId.Q3)
    out = service.calc(CalcRequest(model_id="q3.transition", dataset=ds, params={"scenario": "disorderly"}))
    assert out.metrics["loss_pct"].value >= 0
    assert isinstance(service.validate(ds), list)


def test_same_request_gives_identical_numbers(service):
    ds = service.sample_dataset(QuestionId.Q3)
    a = service.start_run(RunRequest(question=QuestionId.Q3, dataset=ds), wait=True)
    b = service.start_run(RunRequest(question=QuestionId.Q3, dataset=ds), wait=True)
    assert a.input_hash == b.input_hash
    assert service.get_result(a.run_id).comparison == service.get_result(b.run_id).comparison


def test_rest_api_end_to_end(service):
    from fastapi.testclient import TestClient

    from riskbot.api import create_app

    client = TestClient(create_app(service))
    assert client.get("/v2/health").json()["status"] == "ok"
    ds = client.get("/v2/samples/q3_transition").json()
    r = client.post("/v2/runs", json={"question": "q3_transition", "dataset": ds})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    import time

    for _ in range(600):
        status = client.get(f"/v2/runs/{run_id}").json()["status"]
        if status in ("awaiting_review", "failed"):
            break
        time.sleep(0.1)
    assert status == "awaiting_review"
    assert client.get(f"/v2/runs/{run_id}/result").status_code == 200
    assert client.get("/v2/runs/nope").status_code == 404


def test_mcp_end_to_end(service):
    from mcp import Client

    from riskbot.mcp_server import create_server

    async def go():
        async with Client(create_server(service)) as c:
            sc = (await c.call_tool("get_sample_dataset", {"question": "q2_balance_sheet"})).structured_content
            ds = sc.get("result", sc)  # unions and lists are wrapped as {"result": ...} by the MCP SDK
            return await c.call_tool("calculate", {"model_id": "q2.resilience", "dataset": ds,
                                                   "params": {"rate_shock_bp": 300, "run_speed": "fast"}})

    res = asyncio.run(go())
    assert not res.is_error
