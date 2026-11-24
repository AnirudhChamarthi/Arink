"""Resources (models JSON, trace Markdown, report Markdown) and prompts."""

from __future__ import annotations

import json

import pytest
from mcp.shared.exceptions import MCPError

from riskbot.contract import catalog
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.types import QuestionId, ReviewDecision, ReviewSubmission, RunRequest, RunStatus
from riskbot.mcp_server.guidance import PROMPTS
from riskbot.mcp_server.tests.helpers import run_with_client

Q1 = QuestionId.Q1


def _read(server, uri: str):
    result = run_with_client(server, lambda c: c.read_resource(uri))
    (content,) = result.contents
    return content


def _read_error(server, uri: str) -> MCPError:
    """Read ``uri`` expecting a JSON-RPC error; caught inside the session so it is not wrapped."""

    async def body(c):
        try:
            await c.read_resource(uri)
        except MCPError as exc:
            return exc
        raise AssertionError(f"reading {uri} did not fail")

    return run_with_client(server, body)


def _first_trace_id(service, run_id: str) -> str:
    result = service.get_result(run_id)
    return next(v.output for v in result.variations if v.output).traces[0].trace_id


def test_resources_and_templates_listed(server):
    async def body(c):
        return await c.list_resources(), await c.list_resource_templates()

    resources, templates = run_with_client(server, body)
    assert [str(r.uri) for r in resources.resources] == ["riskbot://models"]
    assert {t.uri_template for t in templates.resource_templates} == {
        "riskbot://traces/{trace_id}", "riskbot://reports/{run_id}"}


def test_models_resource_is_json(server):
    content = _read(server, "riskbot://models")
    assert content.mime_type == "application/json"
    specs = json.loads(content.text)
    assert {s["model_id"] for s in specs} == set(catalog.MODEL_SPECS)


def test_trace_resource_markdown(server, service):
    rec = service.start_run(RunRequest(question=Q1, dataset=fake_dataset(Q1)))
    trace_id = _first_trace_id(service, rec.run_id)
    trace = service.get_trace(trace_id)
    content = _read(server, f"riskbot://traces/{trace_id}")
    md = content.text
    assert content.mime_type == "text/markdown"
    assert md.startswith(f"# {trace.title}")
    assert "$$" in md
    assert trace_id in md and trace.input_hash in md
    assert "## Assumptions" in md and trace.assumptions[0] in md
    assert "### 1. " in md and f"### {len(trace.steps)}. " in md
    assert "**Substitution:**" in md and "**Value:**" in md
    assert "## Warnings" in md


def test_trace_resource_unknown(server):
    assert str(_read_error(server, "riskbot://traces/q1.var-000000000000")).startswith("not_found: ")


def test_report_resource_after_human_approval(server, service):
    rec = service.start_run(RunRequest(question=Q1, dataset=fake_dataset(Q1)))
    service.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="Ada"))
    content = _read(server, f"riskbot://reports/{rec.run_id}")
    assert content.mime_type == "text/markdown"
    assert content.text == service.get_report(rec.run_id).markdown
    assert rec.run_id in content.text


def test_report_resource_unknown_run(server):
    assert str(_read_error(server, "riskbot://reports/run-9999")).startswith("not_found: ")


def test_report_resource_conflict_while_running(server, service):
    rec = service.start_run(RunRequest(question=Q1, dataset=fake_dataset(Q1)))
    service.store.update_run(rec.model_copy(update={"status": RunStatus.RUNNING}))
    error = _read_error(server, f"riskbot://reports/{rec.run_id}")
    assert str(error).startswith("conflict: ") and "Traceback" not in str(error)


# ------------------------------------------------------------------------------ prompts


def test_prompts_listed(server):
    prompts = run_with_client(server, lambda c: c.list_prompts()).prompts
    assert {p.name for p in prompts} == {"assess_market_risk", "assess_balance_sheet", "assess_transition_risk"}
    for p in prompts:
        (arg,) = p.arguments
        assert arg.name == "dataset_hint" and arg.required is False and arg.description
        assert p.description


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_prompt_renders_without_hint(server, name):
    question = PROMPTS[name][0]
    result = run_with_client(server, lambda c: c.get_prompt(name, {}))
    (message,) = result.messages
    text = message.content.text
    assert message.role == "user"
    assert f'get_sample_dataset(question="{question.value}")' in text
    for tool in ("validate_dataset", "start_run", "run_result", "get_trace", "get_report"):
        assert tool in text, tool
    assert "trace_id" in text and "SYNTHETIC" in text
    assert "only from tool results" in text


def test_prompt_renders_with_hint(server):
    hint = "my long/short equity book from positions.csv"
    result = run_with_client(server, lambda c: c.get_prompt("assess_market_risk", {"dataset_hint": hint}))
    text = result.messages[0].content.text
    assert hint in text and 'kind="market"' in text
    assert "synthetic" in text.lower()
