"""Happy paths of every /v2 route against ``FakeRunService``, validated against the contract models."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from riskbot.contract import CONTRACT_VERSION, catalog
from riskbot.contract.fakes import FakeRunService
from riskbot.contract.types import (
    AuditEvent,
    DataQualityFinding,
    Dataset,
    ModelOutput,
    ModelSpec,
    QuestionId,
    QuestionInfo,
    Report,
    RunRecord,
    RunResult,
    RunStatus,
    Trace,
)

DATASET = TypeAdapter(Dataset)


def test_health(client: TestClient) -> None:
    r = client.get("/v2/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "contract_version": CONTRACT_VERSION}


def test_questions(client: TestClient) -> None:
    r = client.get("/v2/questions")
    assert r.status_code == 200
    infos = TypeAdapter(list[QuestionInfo]).validate_python(r.json())
    assert [i.question for i in infos] == list(QuestionId)
    assert infos[0].default_plan == catalog.DEFAULT_PLANS[QuestionId.Q1]


def test_models_all_and_filtered(client: TestClient) -> None:
    all_specs = TypeAdapter(list[ModelSpec]).validate_python(client.get("/v2/models").json())
    assert {s.model_id for s in all_specs} == set(catalog.MODEL_SPECS)
    r = client.get("/v2/models", params={"question": "q2_balance_sheet"})
    assert r.status_code == 200
    q2 = TypeAdapter(list[ModelSpec]).validate_python(r.json())
    assert {s.model_id for s in q2} == {"q2.resilience", "q2.reverse_stress", "q2.data_quality"}


@pytest.mark.parametrize("question", list(QuestionId))
def test_samples_round_trip(client: TestClient, service: FakeRunService, question: QuestionId) -> None:
    r = client.get(f"/v2/samples/{question.value}")
    assert r.status_code == 200
    ds = DATASET.validate_python(r.json())
    assert ds == service.sample_dataset(question)


def test_list_runs_limit(client: TestClient, service: FakeRunService) -> None:
    sample = client.get("/v2/samples/q3_transition").json()
    for _ in range(3):
        assert client.post("/v2/runs", json={"question": "q3_transition", "dataset": sample}).status_code == 202
    r = client.get("/v2/runs", params={"limit": 2})
    assert r.status_code == 200
    assert len(TypeAdapter(list[RunRecord]).validate_python(r.json())) == 2
    assert len(client.get("/v2/runs").json()) == 3


def test_calc_with_params(client: TestClient) -> None:
    sample = client.get("/v2/samples/q1_market").json()
    r = client.post("/v2/calc", json={"model_id": "q1.var", "dataset": sample,
                                      "params": {"method": "historical"}, "seed": 7})
    assert r.status_code == 200
    out = ModelOutput.model_validate(r.json())
    assert out.model_id == "q1.var" and out.params["method"] == "historical"
    assert "covariance" not in out.params  # resolve_params dropped the inapplicable parameter


def test_full_flow(client: TestClient, service: FakeRunService) -> None:
    """samples -> validate -> calc -> start run -> poll -> result -> trace -> review -> report -> audit."""
    # 1. sample and validation
    sample = client.get("/v2/samples/q1_market").json()
    r = client.post("/v2/datasets/validate", json=sample)
    assert r.status_code == 200
    findings = TypeAdapter(list[DataQualityFinding]).validate_python(r.json())
    assert findings and findings[0].check == "fake_check"

    # 2. single calculation
    r = client.post("/v2/calc", json={"model_id": "q1.data_quality", "dataset": sample})
    assert r.status_code == 200
    assert ModelOutput.model_validate(r.json()).metrics

    # 3. start the run: 202 + Location
    r = client.post("/v2/runs", json={"question": "q1_market", "dataset": sample, "seed": 11})
    assert r.status_code == 202
    record = RunRecord.model_validate(r.json())
    run_id = record.run_id
    assert r.headers["location"] == f"/v2/runs/{run_id}"
    assert record.synthetic is True

    # 4. poll until awaiting_review (the fake finishes synchronously)
    for _ in range(10):
        status = RunRecord.model_validate(client.get(f"/v2/runs/{run_id}").json()).status
        if status in (RunStatus.AWAITING_REVIEW, RunStatus.FAILED):
            break
    assert status == RunStatus.AWAITING_REVIEW
    assert [x["run_id"] for x in client.get("/v2/runs").json()] == [run_id]

    # 5. result
    r = client.get(f"/v2/runs/{run_id}/result")
    assert r.status_code == 200
    result = RunResult.model_validate(r.json())
    assert result.run.run_id == run_id
    assert result.plan == catalog.DEFAULT_PLANS[QuestionId.Q1]
    assert len(result.variations) == record.n_variations

    # 6. trace of the first metric
    metric = next(iter(result.variations[0].output.metrics.values()))
    r = client.get(f"/v2/traces/{metric.trace_id}")
    assert r.status_code == 200
    trace = Trace.model_validate(r.json())
    assert trace.trace_id == metric.trace_id
    assert any(s.id == metric.trace_step and s.value == metric.value for s in trace.steps)

    # 7. review with a factor edit
    review = {"decision": "approve", "reviewer": "Ana Analyst", "comment": "ok",
              "factor_edits": [{"factor_id": "fake_factor", "likelihood": 4, "reason": "recent stress"}]}
    r = client.post(f"/v2/runs/{run_id}/review", json=review)
    assert r.status_code == 200
    assert RunRecord.model_validate(r.json()).status == RunStatus.APPROVED

    # 8. report as JSON
    r = client.get(f"/v2/runs/{run_id}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    report = Report.model_validate(r.json())
    assert report.signoff is not None and report.signoff.reviewer == "Ana Analyst"
    assert report.assessment.factors[0].likelihood == 4
    assert client.get(f"/v2/runs/{run_id}/report", params={"format": "json"}).json() == r.json()

    # 9. report as Markdown
    r = client.get(f"/v2/runs/{run_id}/report", params={"format": "md"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text == report.markdown and r.text.startswith(f"# Run {run_id}")

    # 10. audit (the fake records none itself; add one to check serialisation)
    assert client.get(f"/v2/runs/{run_id}/audit").json() == []
    service.store.append_audit(AuditEvent(run_id=run_id, at=dt.datetime(2026, 11, 24, tzinfo=dt.timezone.utc),
                                          actor="system", event="status", detail={"to": "approved"}))
    r = client.get(f"/v2/runs/{run_id}/audit")
    assert r.status_code == 200
    events = TypeAdapter(list[AuditEvent]).validate_python(r.json())
    assert [e.event for e in events] == ["status"]


def test_start_run_uses_wait_false(service: FakeRunService) -> None:
    """POST /v2/runs must not block: it calls start_run(wait=False)."""
    from riskbot.api import create_app

    calls: list[bool] = []
    original = service.start_run

    def spy(request, *, wait=False):  # type: ignore[no-untyped-def]
        calls.append(wait)
        return original(request, wait=wait)

    service.start_run = spy  # type: ignore[method-assign]
    client = TestClient(create_app(service))
    sample = client.get("/v2/samples/q2_balance_sheet").json()
    assert client.post("/v2/runs", json={"question": "q2_balance_sheet", "dataset": sample}).status_code == 202
    assert calls == [False]
