"""OpenAPI completeness and CORS behaviour."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riskbot.api import create_app
from riskbot.contract import CONTRACT_VERSION
from riskbot.contract.fakes import FakeRunService

# CONTRACT.md 6.1: (method, path) -> (response schema ref or None, request body schema or None)
ROUTES = {
    ("get", "/v2/health"): ("Health", None),
    ("get", "/v2/questions"): ("QuestionInfo", None),
    ("get", "/v2/models"): ("ModelSpec", None),
    ("get", "/v2/samples/{question}"): ("MarketDataset", None),
    ("post", "/v2/datasets/validate"): ("DataQualityFinding", "MarketDataset"),
    ("post", "/v2/calc"): ("ModelOutput", "CalcRequest"),
    ("post", "/v2/runs"): ("RunRecord", "RunRequest"),
    ("get", "/v2/runs"): ("RunRecord", None),
    ("get", "/v2/runs/{run_id}"): ("RunRecord", None),
    ("get", "/v2/runs/{run_id}/result"): ("RunResult", None),
    ("get", "/v2/runs/{run_id}/audit"): ("AuditEvent", None),
    ("post", "/v2/runs/{run_id}/review"): ("RunRecord", "ReviewSubmission"),
    ("get", "/v2/runs/{run_id}/report"): ("Report", None),
    ("get", "/v2/traces/{trace_id}"): ("Trace", None),
}

CONTRACT_SCHEMAS = {
    "QuestionInfo", "QuestionPlan", "ModelSpec", "ParamSpec", "MetricSpec", "MarketDataset", "BankBalanceSheet",
    "ClimatePortfolio", "DataQualityFinding", "CalcRequest", "ModelOutput", "Metric", "Trace", "TraceStep",
    "RunRequest", "RunRecord", "RunResult", "VariationResult", "Comparison", "QualitativeAssessment",
    "AuditEvent", "ReviewSubmission", "FactorEdit", "Report", "SignOff", "ErrorBody", "QuestionId",
}


@pytest.fixture(scope="module")
def spec() -> dict:  # type: ignore[type-arg]
    r = TestClient(create_app(FakeRunService())).get("/v2/openapi.json")
    assert r.status_code == 200
    return r.json()


def test_info(spec: dict) -> None:  # type: ignore[type-arg]
    assert spec["info"]["title"] == "Riskbot v2 API"
    assert spec["info"]["version"] == CONTRACT_VERSION


def test_exactly_the_contract_routes(spec: dict) -> None:  # type: ignore[type-arg]
    found = {(m, p) for p, ops in spec["paths"].items() for m in ops}
    assert found == set(ROUTES)


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_route_schemas(spec: dict, route: tuple[str, str]) -> None:  # type: ignore[type-arg]
    method, path = route
    op = spec["paths"][path][method]
    response_ref, body_ref = ROUTES[route]
    ok = "202" if route == ("post", "/v2/runs") else "200"
    assert f"#/components/schemas/{response_ref}" in str(op["responses"][ok])
    if body_ref:
        assert f"#/components/schemas/{body_ref}" in str(op["requestBody"])
    # every error status documents ErrorBody; FastAPI's default HTTPValidationError is replaced
    for status, resp in op["responses"].items():
        if status not in ("200", "202"):
            assert "#/components/schemas/ErrorBody" in str(resp), (route, status)
    assert "HTTPValidationError" not in str(op)


def test_report_documents_markdown(spec: dict) -> None:  # type: ignore[type-arg]
    content = spec["paths"]["/v2/runs/{run_id}/report"]["get"]["responses"]["200"]["content"]
    assert {"application/json", "text/markdown"} <= set(content)


def test_dataset_body_is_discriminated(spec: dict) -> None:  # type: ignore[type-arg]
    schema = spec["paths"]["/v2/datasets/validate"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["discriminator"]["propertyName"] == "kind"


def test_contract_schemas_present(spec: dict) -> None:  # type: ignore[type-arg]
    assert CONTRACT_SCHEMAS <= set(spec["components"]["schemas"])


def test_docs_served() -> None:
    client = TestClient(create_app(FakeRunService()))
    r = client.get("/v2/docs")
    assert r.status_code == 200 and "/v2/openapi.json" in r.text


# ------------------------------------------------------------------ CORS


def test_cors_default_origin_allowed(client: TestClient) -> None:
    r = client.get("/v2/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight(client: TestClient) -> None:
    r = client.options("/v2/runs", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in r.headers["access-control-allow-methods"]


def test_cors_other_origin_not_allowed(client: TestClient) -> None:
    r = client.get("/v2/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_override() -> None:
    client = TestClient(create_app(FakeRunService(), cors_origins=["https://riskbot.example"]))
    ok = client.get("/v2/health", headers={"Origin": "https://riskbot.example"})
    assert ok.headers["access-control-allow-origin"] == "https://riskbot.example"
    old = client.get("/v2/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in old.headers


def test_cors_on_error_responses(client: TestClient) -> None:
    r = client.get("/v2/runs/nope", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 404
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    big = client.post("/v2/calc", content=b" " * (10 * 1024 * 1024 + 1),
                      headers={"Origin": "http://localhost:5173", "content-type": "application/json"})
    assert big.status_code == 413
    assert big.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "location" in client.post(
        "/v2/runs", json={"question": "q1_market", "dataset": client.get("/v2/samples/q1_market").json()},
        headers={"Origin": "http://localhost:5173"}).headers["access-control-expose-headers"].lower()
