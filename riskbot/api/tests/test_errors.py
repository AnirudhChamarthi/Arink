"""Error mapping: every failure is an ``ErrorBody`` with the status of its contract exception."""

from __future__ import annotations

import datetime as dt
import logging

import pytest
from fastapi.testclient import TestClient

from riskbot.api import create_app
from riskbot.api.limits import MAX_BODY_BYTES
from riskbot.contract import catalog
from riskbot.contract.errors import RiskbotError
from riskbot.contract.fakes import FakeRunService
from riskbot.contract.types import ErrorBody, RunStatus


def assert_error(r, status: int, code: str) -> ErrorBody:  # type: ignore[no-untyped-def]
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = ErrorBody.model_validate(r.json())
    assert body.code == code
    assert body.message
    return body


def _start(client: TestClient, question: str = "q1_market") -> str:
    sample = client.get(f"/v2/samples/{question}").json()
    return client.post("/v2/runs", json={"question": question, "dataset": sample}).json()["run_id"]


# ------------------------------------------------------------------ 404


@pytest.mark.parametrize("path", ["/v2/runs/nope", "/v2/runs/nope/result", "/v2/runs/nope/audit",
                                  "/v2/runs/nope/report", "/v2/traces/q1.var-000000000000"])
def test_not_found_gets(client: TestClient, path: str) -> None:
    assert_error(client.get(path), 404, "not_found")


def test_not_found_review(client: TestClient) -> None:
    assert_error(client.post("/v2/runs/nope/review", json={"decision": "approve", "reviewer": "x"}), 404, "not_found")


def test_unknown_model_in_calc_is_404(client: TestClient) -> None:
    sample = client.get("/v2/samples/q1_market").json()
    body = assert_error(client.post("/v2/calc", json={"model_id": "q9.magic", "dataset": sample}), 404, "not_found")
    assert "q9.magic" in body.message


def test_unknown_route_is_error_body(client: TestClient) -> None:
    assert_error(client.get("/v2/nowhere"), 404, "not_found")


def test_wrong_method_is_error_body(client: TestClient) -> None:
    assert_error(client.delete("/v2/health"), 405, "validation_failed")


# ------------------------------------------------------------------ 409


def test_review_on_approved_run_is_409(client: TestClient) -> None:
    run_id = _start(client)
    review = {"decision": "approve", "reviewer": "Ana"}
    assert client.post(f"/v2/runs/{run_id}/review", json=review).status_code == 200
    body = assert_error(client.post(f"/v2/runs/{run_id}/review", json=review), 409, "conflict")
    assert "approved" in body.message


def test_result_and_report_of_running_run_are_409(client: TestClient, service: FakeRunService) -> None:
    run_id = _start(client)
    rec = service.store.get_run(run_id)
    service.store.update_run(rec.model_copy(update={"status": RunStatus.RUNNING}))
    assert_error(client.get(f"/v2/runs/{run_id}/result"), 409, "conflict")
    assert_error(client.get(f"/v2/runs/{run_id}/report"), 409, "conflict")
    assert_error(client.get(f"/v2/runs/{run_id}/report", params={"format": "md"}), 409, "conflict")


# ------------------------------------------------------------------ 422


@pytest.mark.parametrize("path,params", [("/v2/samples/q4_nonsense", None), ("/v2/models", {"question": "q4"})])
def test_unknown_question_is_422(client: TestClient, path: str, params) -> None:  # type: ignore[no-untyped-def]
    body = assert_error(client.get(path, params=params), 422, "validation_failed")
    errors = body.details["errors"]
    assert errors and errors[0]["type"] == "enum"
    assert set(errors[0]) == {"loc", "msg", "type"}


def test_bad_body_is_422_without_echoing_input(client: TestClient) -> None:
    sample = client.get("/v2/samples/q1_market").json()
    sample["positions"][0]["price"] = -1
    body = assert_error(client.post("/v2/datasets/validate", json=sample), 422, "validation_failed")
    locs = [e["loc"] for e in body.details["errors"]]
    assert ["body", "market", "positions", 0, "price"] in locs
    assert "input" not in str(body.details)


def test_unknown_field_and_unknown_kind_are_422(client: TestClient) -> None:
    sample = client.get("/v2/samples/q3_transition").json()
    assert_error(client.post("/v2/datasets/validate", json={**sample, "extra": 1}), 422, "validation_failed")
    assert_error(client.post("/v2/datasets/validate", json={**sample, "kind": "crypto"}), 422, "validation_failed")


def test_malformed_json_is_422(client: TestClient) -> None:
    r = client.post("/v2/calc", content=b"{not json", headers={"content-type": "application/json"})
    assert_error(r, 422, "validation_failed")


def test_bad_query_values_are_422(client: TestClient) -> None:
    assert_error(client.get("/v2/runs", params={"limit": 0}), 422, "validation_failed")
    run_id = _start(client)
    assert_error(client.get(f"/v2/runs/{run_id}/report", params={"format": "pdf"}), 422, "validation_failed")


def test_service_validation_failed_is_422(client: TestClient) -> None:
    sample = client.get("/v2/samples/q1_market").json()
    r = client.post("/v2/calc", json={"model_id": "q1.var", "dataset": sample, "params": {"method": "magic"}})
    assert_error(r, 422, "validation_failed")
    plan = catalog.DEFAULT_PLANS[catalog.Q2].model_dump(mode="json")
    r = client.post("/v2/runs", json={"question": "q1_market", "dataset": sample, "plan": plan})
    assert_error(r, 422, "validation_failed")


def test_empty_reviewer_is_422(client: TestClient) -> None:
    run_id = _start(client)
    r = client.post(f"/v2/runs/{run_id}/review", json={"decision": "approve", "reviewer": ""})
    assert_error(r, 422, "validation_failed")


# ------------------------------------------------------------------ 413


def test_body_above_10_mb_is_413(client: TestClient) -> None:
    r = client.post("/v2/calc", content=b" " * (MAX_BODY_BYTES + 1), headers={"content-type": "application/json"})
    body = assert_error(r, 413, "limit_exceeded")
    assert body.details["maximum"] == MAX_BODY_BYTES


def test_chunked_body_above_10_mb_is_413(client: TestClient) -> None:
    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(11):
            yield b" " * (1024 * 1024)

    r = client.post("/v2/datasets/validate", content=chunks(), headers={"content-type": "application/json"})
    assert_error(r, 413, "limit_exceeded")


def _many_cash_positions(n: int) -> dict:  # type: ignore[type-arg]
    return {"kind": "market", "name": "big", "as_of": "2026-11-01", "synthetic": True, "dates": [], "returns": {},
            "positions": [{"ticker": f"C{i}", "asset_class": "cash", "quantity": 1, "price": 1} for i in range(n)]}


def test_too_many_positions_is_413_on_every_dataset_route(client: TestClient) -> None:
    ds = _many_cash_positions(catalog.LIMITS["max_positions"] + 1)
    for path, body in [("/v2/datasets/validate", ds),
                       ("/v2/calc", {"model_id": "q1.var", "dataset": ds}),
                       ("/v2/runs", {"question": "q1_market", "dataset": ds})]:
        err = assert_error(client.post(path, json=body), 413, "limit_exceeded")
        assert err.details["limit"] == "max_positions"
    assert client.get("/v2/runs").json() == []  # nothing reached the service


def test_dataset_at_limit_is_accepted(client: TestClient) -> None:
    ds = _many_cash_positions(catalog.LIMITS["max_positions"])
    assert client.post("/v2/datasets/validate", json=ds).status_code == 200


def test_too_long_history_is_413(client: TestClient) -> None:
    n = catalog.LIMITS["max_history_days"] + 1
    dates = [(dt.date(2000, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(n)]
    ds = {"kind": "market", "name": "long", "as_of": dates[-1], "synthetic": True, "dates": dates,
          "returns": {"AAA": [0.0] * n}, "positions": [{"ticker": "AAA", "quantity": 1, "price": 1}]}
    err = assert_error(client.post("/v2/datasets/validate", json=ds), 413, "limit_exceeded")
    assert err.details["limit"] == "max_history_days"


def test_too_many_holdings_and_balance_sheet_items_are_413(client: TestClient) -> None:
    climate = client.get("/v2/samples/q3_transition").json()
    climate["holdings"] = climate["holdings"][:1] * (catalog.LIMITS["max_holdings"] + 1)
    assert_error(client.post("/v2/datasets/validate", json=climate), 413, "limit_exceeded")

    bank = client.get("/v2/samples/q2_balance_sheet").json()
    bank["assets"] = bank["assets"][:1] * catalog.LIMITS["max_balance_sheet_items"]
    err = assert_error(client.post("/v2/datasets/validate", json=bank), 413, "limit_exceeded")
    assert err.details["limit"] == "max_balance_sheet_items"


def test_oversized_plan_is_413(client: TestClient) -> None:
    sample = client.get("/v2/samples/q3_transition").json()
    plan = {"question": "q3_transition",
            "grid": {"model_id": "q3.transition", "dimensions": {"horizon_years": list(range(1, 31)),
                                                                 "n_sims": list(range(100, 3600, 100))}}}
    err = assert_error(client.post("/v2/runs", json={"question": "q3_transition", "dataset": sample, "plan": plan}),
                       413, "limit_exceeded")
    assert err.details == {"limit": "max_variations", "value": 30 * 35, "maximum": 1000}


# ------------------------------------------------------------------ 500


class _Exploding(FakeRunService):
    def questions(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("secret database password in /etc/riskbot")

    def list_runs(self, limit: int = 100):  # type: ignore[no-untyped-def]
        raise RiskbotError("base error from a service")


def test_unexpected_exception_is_500_without_leak(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(create_app(_Exploding()), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="riskbot.api"):
        r = client.get("/v2/questions", headers={"Origin": "http://localhost:5173"})
    body = assert_error(r, 500, "internal")
    assert "secret" not in r.text and "RuntimeError" not in r.text
    assert body.details == {"request": "GET /v2/questions"}
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"  # CORS even on 500
    assert any("secret" in (rec.exc_text or "") or rec.exc_info for rec in caplog.records)


def test_base_riskbot_error_is_500_internal() -> None:
    client = TestClient(create_app(_Exploding()), raise_server_exceptions=False)
    assert_error(client.get("/v2/runs"), 500, "internal")
