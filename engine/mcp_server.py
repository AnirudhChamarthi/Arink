"""Riskbot MCP server — read-only risk calculations with step-by-step math traces.

Run locally over stdio (the default for Claude Desktop / Claude Code):

    python mcp_server.py

The server only exposes deterministic calculations from ``models``. The AI client chooses which
calculation to run and explains the result; every figure and every step comes from the engine.
Nothing here writes to disk or calls the network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ENGINE_ROOT = Path(__file__).resolve().parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from models.explain import explain_parametric_var, explain_stress  # noqa: E402
from models.stress import _load_scenarios  # noqa: E402
from schemas.contract import EnrichedPortfolio, StressScenario  # noqa: E402

MAX_POSITIONS = 500
MAX_HORIZON_DAYS = 250

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    name="riskbot",
    instructions=(
        "Deterministic portfolio risk calculations. Each tool returns the result together with a "
        "step-by-step math trace (formulas, substituted numbers, assumptions, input hash). Quote "
        "numbers only from tool results; never estimate a risk figure yourself. A portfolio must "
        "include daily returns (returns_252d) for each position."
    ),
)


def _check_portfolio(portfolio: EnrichedPortfolio) -> None:
    if len(portfolio.positions) > MAX_POSITIONS:
        raise ValueError(f"Portfolio has {len(portfolio.positions)} positions; the limit is {MAX_POSITIONS}.")


def _package(trace) -> dict[str, Any]:
    return {
        "trace_id": trace.trace_id,
        "result": trace.result,
        "warnings": trace.warnings,
        "markdown": trace.to_markdown(),
        "trace": trace.to_dict(),
    }


@server.tool(title="Parametric VaR with math trace", annotations=_READ_ONLY)
def var_trace(portfolio: EnrichedPortfolio, confidence: float = 0.99, horizon_days: int = 1) -> dict[str, Any]:
    """Variance-covariance (normal) VaR and expected shortfall, with every step shown.

    Results are fractions of gross exposure; ``var_amount`` is in the portfolio currency.
    """
    if not 0.5 < confidence < 1.0:
        raise ValueError("confidence must be between 0.5 and 1 (exclusive), e.g. 0.99.")
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}.")
    _check_portfolio(portfolio)
    return _package(explain_parametric_var(portfolio, confidence, horizon_days))


@server.tool(title="Stress test with math trace", annotations=_READ_ONLY)
def stress_trace(
    portfolio: EnrichedPortfolio,
    scenario: str,
    custom_shocks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Scenario stress P&L. Use a named scenario (see list_stress_scenarios) or 'custom' with
    custom_shocks mapping a sector or asset class to a return, e.g. {"Equity": -0.30}."""
    try:
        sc = StressScenario(scenario)
    except ValueError:
        raise ValueError(f"Unknown scenario '{scenario}'. Use list_stress_scenarios to see the options.") from None
    _check_portfolio(portfolio)
    return _package(explain_stress(portfolio, sc, custom_shocks))


@server.tool(title="List stress scenarios", annotations=_READ_ONLY)
def list_stress_scenarios() -> dict[str, Any]:
    """Named stress scenarios and their shocks, plus the 'custom' option."""
    catalog = _load_scenarios()
    return {
        "scenarios": {
            name: {"description": e.get("description", ""), "shocks": e.get("shocks", {})}
            for name, e in catalog.items()
        },
        "custom": "Pass scenario='custom' and custom_shocks={'Equity': -0.30, 'Technology': -0.40}.",
    }


@server.resource("riskbot://docs/models", mime_type="text/markdown", title="Model documentation")
def model_docs() -> str:
    """The engine's model README: formulas and assumptions."""
    readme = _ENGINE_ROOT / "models" / "README.md"
    return readme.read_text(encoding="utf-8") if readme.is_file() else "Model documentation not found."


if __name__ == "__main__":
    server.run()  # stdio transport
