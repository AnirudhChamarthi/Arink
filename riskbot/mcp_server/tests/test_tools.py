"""Tools of the MCP server: list, annotations, behaviour against FakeRunService, errors."""

from __future__ import annotations

import re

from riskbot.contract import catalog
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.types import (
    DataQualityFinding,
    ModelOutput,
    QuestionId,
    QuestionInfo,
    Report,
    RunRecord,
    RunRequest,
    RunResult,
    RunStatus,
    Trace,
)
from riskbot.mcp_server.server import TOOL_NAMES
from riskbot.mcp_server.tests.helpers import call, error_text, run_with_client

Q1, Q2, Q3 = QuestionId.Q1, QuestionId.Q2, QuestionId.Q3


def _dataset_json(question: QuestionId) -> dict:
    return fake_dataset(question).model_dump(mode="json")


def _tools(server) -> dict:
    result = run_with_client(server, lambda c: c.list_tools())
    return {t.name: t for t in result.tools}


# ------------------------------------------------------------------------------ listing & annotations


def test_tool_list_is_exactly_contract_6_2(server):
    assert set(_tools(server)) == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 10


def test_annotations_read_only_except_start_run(server):
    tools = _tools(server)
    for name, tool in tools.items():
        a = tool.annotations
        assert a is not None, name
        if name == "start_run":
            assert a.read_only_hint is False
            assert a.destructive_hint is False
            assert a.open_world_hint is False
        else:
            assert a.read_only_hint is True, name
            assert a.idempotent_hint is True, name
            assert a.open_world_hint is False, name


def test_no_review_or_signoff_tool(server):
    forbidden = re.compile(r"review|approv|sign_?off|reject|submit|decision", re.IGNORECASE)
    assert not [n for n in _tools(server) if forbidden.search(n)]


def test_schemas_use_contract_types(server):
    tools = _tools(server)
    start = tools["start_run"].input_schema
    assert set(start["properties"]) == {"question", "dataset", "plan", "seed", "wait"}
    assert set(start["required"]) == {"question", "dataset"}
    assert start["properties"]["wait"]["default"] is True
    defs = start["$defs"]
    for model in ("MarketDataset", "BankBalanceSheet", "ClimatePortfolio", "QuestionPlan", "GridSpec"):
        assert model in defs, model
    assert "wait defaults to TRUE" in tools["start_run"].description
    calc = tools["calculate"].input_schema
    assert set(calc["required"]) == {"model_id", "dataset"}
    # structured output: every tool advertises an output schema
    assert all(t.output_schema for t in tools.values())
    assert "SYNTHETIC" in tools["get_sample_dataset"].description


def test_server_instructions(server):
    text = server.instructions
    assert "trace_id" in text
    assert "synthetic" in text.lower()
    assert "ONLY from tool results" in text
    assert "human-only" in text


# ------------------------------------------------------------------------------ each tool


def test_list_questions(server):
    r = call(server, "list_questions")
    assert not r.is_error
    infos = [QuestionInfo.model_validate(x) for x in r.structured_content["result"]]
    assert {i.question for i in infos} == {Q1, Q2, Q3}


def test_list_models_all_and_filtered(server):
    r = call(server, "list_models")
    assert {m["model_id"] for m in r.structured_content["result"]} == set(catalog.MODEL_SPECS)
    r = call(server, "list_models", {"question": "q2_balance_sheet"})
    assert {m["model_id"] for m in r.structured_content["result"]} == {
        "q2.resilience", "q2.reverse_stress", "q2.data_quality"}


def test_get_sample_dataset_is_synthetic(server):
    for q in QuestionId:
        r = call(server, "get_sample_dataset", {"question": q.value})
        assert not r.is_error
        ds = r.structured_content["result"]
        assert ds["kind"] == catalog.QUESTIONS[q].dataset_kind.value
        assert ds["synthetic"] is True


def test_validate_dataset(server, service):
    r = call(server, "validate_dataset", {"dataset": _dataset_json(Q3)})
    assert not r.is_error
    findings = [DataQualityFinding.model_validate(f) for f in r.structured_content["result"]]
    assert findings and findings[0].check == "fake_check"
    assert service.calls[-1][0] == "validate"


def test_calculate_returns_traced_metrics(server, service):
    r = call(server, "calculate", {"model_id": "q2.resilience", "dataset": _dataset_json(Q2),
                                   "params": {"rate_shock_bp": 300}, "seed": 7})
    assert not r.is_error
    out = ModelOutput.model_validate(r.structured_content)
    assert out.params["rate_shock_bp"] == 300
    trace_ids = {t.trace_id for t in out.traces}
    assert out.metrics and all(m.trace_id in trace_ids for m in out.metrics.values())
    request = service.calls[-1][1]["request"]
    assert request.seed == 7


def test_start_run_defaults_to_wait_true(server, service):
    r = call(server, "start_run", {"question": "q1_market", "dataset": _dataset_json(Q1)})
    assert not r.is_error
    rec = RunRecord.model_validate(r.structured_content)
    assert rec.status == RunStatus.AWAITING_REVIEW
    name, kwargs = service.calls[-1]
    assert name == "start_run" and kwargs["wait"] is True
    assert kwargs["request"].plan is None
    assert kwargs["request"].seed == 20261123


def test_start_run_passes_plan_seed_and_wait(server, service):
    plan = catalog.DEFAULT_PLANS[Q3].model_copy(update={"extras": []}).model_dump(mode="json")
    plan["grid"]["dimensions"] = {"scenario": ["orderly", "hot_house"]}
    r = call(server, "start_run", {"question": "q3_transition", "dataset": _dataset_json(Q3), "plan": plan,
                                   "seed": 11, "wait": False})
    assert not r.is_error
    assert r.structured_content["n_variations"] == 2
    kwargs = service.calls[-1][1]
    assert kwargs["wait"] is False and kwargs["request"].seed == 11
    assert kwargs["request"].plan.grid.dimensions == {"scenario": ["orderly", "hot_house"]}


def test_full_flow(server, service):
    """sample -> validate -> calculate -> start_run -> run_status -> run_result -> get_trace -> get_report."""

    async def flow(c):
        ds = (await c.call_tool("get_sample_dataset", {"question": "q1_market"})).structured_content["result"]
        v = await c.call_tool("validate_dataset", {"dataset": ds})
        assert not v.is_error
        calc = await c.call_tool("calculate", {"model_id": "q1.var", "dataset": ds, "params": {"method": "evt"}})
        assert not calc.is_error and calc.structured_content["params"]["method"] == "evt"
        rec = (await c.call_tool("start_run", {"question": "q1_market", "dataset": ds})).structured_content
        assert rec["synthetic"] is True
        status = (await c.call_tool("run_status", {"run_id": rec["run_id"]})).structured_content
        assert status["status"] == "awaiting_review"
        res = RunResult.model_validate((await c.call_tool("run_result", {"run_id": rec["run_id"]})).structured_content)
        assert res.comparison.metric_ranges and len(res.variations) == rec["n_variations"]
        metric = next(v.output for v in res.variations if v.output).metrics["var"]
        tr = await c.call_tool("get_trace", {"trace_id": metric.trace_id})
        trace = Trace.model_validate(tr.structured_content)
        step = next(s for s in trace.steps if s.id == metric.trace_step)
        assert step.value == metric.value
        rep = Report.model_validate((await c.call_tool("get_report", {"run_id": rec["run_id"]})).structured_content)
        assert rep.run.run_id == rec["run_id"] and rep.markdown
        return rec

    rec = run_with_client(server, flow)
    assert service.get_run(rec["run_id"]).status == RunStatus.AWAITING_REVIEW  # nothing signed off


# ------------------------------------------------------------------------------ errors


def test_unknown_run_is_not_found(server):
    for tool in ("run_status", "run_result", "get_report"):
        text = error_text(call(server, tool, {"run_id": "run-9999"}))
        assert text.startswith("not_found: "), text
        assert "run-9999" in text


def test_unknown_trace_is_not_found(server):
    assert error_text(call(server, "get_trace", {"trace_id": "q1.var-000000000000"})).startswith("not_found: ")


def test_unknown_model_is_not_found(server):
    text = error_text(call(server, "calculate", {"model_id": "q9.nope", "dataset": _dataset_json(Q1)}))
    assert text.startswith("not_found: ") and "q9.nope" in text


def test_invalid_params_are_validation_failed(server):
    text = error_text(call(server, "calculate", {"model_id": "q1.var", "dataset": _dataset_json(Q1),
                                                  "params": {"confidence": 5}}))
    assert text.startswith("validation_failed: ") and "confidence" in text
    text = error_text(call(server, "calculate", {"model_id": "q1.var", "dataset": _dataset_json(Q1),
                                                  "params": {"no_such_param": 1}}))
    assert text.startswith("validation_failed: ")


def test_wrong_dataset_kind_for_question(server, service):
    text = error_text(call(server, "start_run", {"question": "q2_balance_sheet", "dataset": _dataset_json(Q1)}))
    assert text.startswith("validation_failed: ") and "balance_sheet" in text
    assert not [c for c in service.calls if c[0] == "start_run"]


def test_plan_for_other_question(server):
    plan = catalog.DEFAULT_PLANS[Q3].model_dump(mode="json")
    text = error_text(call(server, "start_run", {"question": "q1_market", "dataset": _dataset_json(Q1),
                                                 "plan": plan}))
    assert text.startswith("validation_failed: ")


def test_schema_violations_rejected_by_sdk(server):
    bad = _dataset_json(Q1)
    del bad["positions"]
    r = call(server, "validate_dataset", {"dataset": bad})
    assert r.is_error and "positions" in error_text(r)
    assert call(server, "list_models", {"question": "q9"}).is_error
    assert call(server, "run_status", {}).is_error


def test_conflict_while_running(server, service):
    rec = service.start_run(RunRequest(question=Q1, dataset=fake_dataset(Q1)))
    service.store.update_run(rec.model_copy(update={"status": RunStatus.RUNNING}))
    for tool in ("run_result", "get_report"):
        assert error_text(call(server, tool, {"run_id": rec.run_id})).startswith("conflict: ")


def test_unexpected_exception_is_internal_without_traceback(server, service):
    def boom(question=None):
        raise RuntimeError("secret internal detail")

    service.list_models = boom
    text = error_text(call(server, "list_models"))
    assert text.startswith("internal: ")
    assert "secret" not in text and "Traceback" not in text
