"""The MCP server exposes read-only tools that return the same numbers as the engine."""

import asyncio

import numpy as np
import pytest
from mcp import Client

import mcp_server
from models.var import parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _pf(n=2, qty=100.0):
    rng = np.random.default_rng(11)
    positions = [
        EnrichedPosition(
            ticker=f"T{i}", asset_class=AssetClass.EQUITY, quantity=qty if i % 2 == 0 else -qty / 2,
            cost_price=100.0, currency="USD", current_price=100.0,
            returns_252d=rng.normal(0, 0.01 + 0.002 * i, 252).tolist(), implied_vol=0.25,
            risk_free_rate=0.04, esg_score=60.0, carbon_intensity=50.0,
        )
        for i in range(n)
    ]
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=positions)


def _call(name, args):
    async def go():
        async with Client(mcp_server.server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def _sc(result):
    return result.structured_content


def test_tools_are_registered_and_read_only():
    async def go():
        async with Client(mcp_server.server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert {"var_trace", "stress_trace", "list_stress_scenarios"} <= set(tools)
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())


def test_var_trace_returns_the_engine_number_and_a_trace():
    pf = _pf()
    out = _sc(_call("var_trace", {"portfolio": pf.model_dump(mode="json"), "confidence": 0.99, "horizon_days": 10}))
    assert out["result"]["var"] == pytest.approx(parametric_var(pf, 0.99, 10).var, rel=1e-12)
    assert out["trace_id"].startswith("parametric_var-")
    assert "$$" in out["markdown"] and out["trace"]["steps"]


def test_stress_trace_with_custom_shocks():
    pf = _pf()
    out = _sc(_call("stress_trace", {"portfolio": pf.model_dump(mode="json"), "scenario": "custom",
                                     "custom_shocks": {"Equity": -0.2}}))
    # T0 long 100 @ 100 = +10000 * -0.2, T1 short 50 @ 100 = -5000 * -0.2
    assert out["result"]["portfolio_pnl"] == pytest.approx(-2000.0 + 1000.0)


def test_list_stress_scenarios_includes_the_catalogue():
    out = _sc(_call("list_stress_scenarios", {}))
    assert "2008_credit" in out["scenarios"]


@pytest.mark.parametrize(
    "args",
    [
        {"confidence": 1.5},
        {"confidence": 0.99, "horizon_days": 0},
        {"confidence": 0.99, "horizon_days": 10_000},
    ],
)
def test_invalid_var_arguments_are_reported_as_tool_errors(args):
    res = _call("var_trace", {"portfolio": _pf().model_dump(mode="json"), **args})
    assert res.is_error


def test_unknown_scenario_and_oversized_portfolio_are_tool_errors():
    assert _call("stress_trace", {"portfolio": _pf().model_dump(mode="json"), "scenario": "nope"}).is_error
    big = _pf(n=mcp_server.MAX_POSITIONS + 1)
    assert _call("var_trace", {"portfolio": big.model_dump(mode="json")}).is_error


def test_model_docs_resource_is_readable():
    async def go():
        async with Client(mcp_server.server) as client:
            return await client.read_resource("riskbot://docs/models")

    res = asyncio.run(go())
    assert "Risk modes" in res.contents[0].text
