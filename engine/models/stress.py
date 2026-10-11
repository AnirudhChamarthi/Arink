"""Named and custom scenario stress tests."""

from __future__ import annotations

import json
from pathlib import Path

from models.portfolio_utils import gross_exposure, position_signed_value
from schemas.contract import EnrichedPortfolio, StressPositionResult, StressResult, StressScenario

_SCENARIOS_PATH = Path(__file__).resolve().parents[2] / "shared" / "scenarios.json"


def _load_scenarios() -> dict:
    if not _SCENARIOS_PATH.is_file():
        return {}
    return json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))


def _shock_for_position(
    pos,
    shocks: dict[str, float],
) -> float:
    sector = (pos.sector or "").strip()
    asset = pos.asset_class.value
    if sector and sector in shocks:
        return float(shocks[sector])
    if asset in shocks:
        return float(shocks[asset])
    return float(shocks.get("Equity", -0.10))


def run_stress(
    portfolio: EnrichedPortfolio,
    scenario: StressScenario,
    custom_shocks: dict[str, float] | None = None,
) -> StressResult:
    if scenario == StressScenario.CUSTOM:
        shocks = dict(custom_shocks or {})
        if not shocks:
            raise ValueError("custom scenario requires custom_shocks.")
        scenario_name = "custom"
    else:
        catalog = _load_scenarios()
        entry = catalog.get(scenario.value)
        if entry is None:
            raise ValueError(f"Unknown stress scenario: {scenario.value}")
        shocks = dict(entry.get("shocks") or {})
        scenario_name = scenario.value

    # P&L uses signed market values, so a short position gains when its shock is negative.
    # Percentages are relative to gross exposure (equal to the portfolio value when long-only).
    total_mv = gross_exposure(portfolio) or 1.0
    results: list[StressPositionResult] = []

    for pos in portfolio.positions:
        mv = position_signed_value(pos)
        shock = _shock_for_position(pos, shocks)
        pnl = mv * shock
        pct = pnl / total_mv
        results.append(
            StressPositionResult(ticker=pos.ticker, pnl_impact=pnl, pct_impact=pct)
        )

    portfolio_pnl = sum(r.pnl_impact for r in results)
    portfolio_pct = portfolio_pnl / total_mv
    worst = sorted(results, key=lambda r: r.pnl_impact)[:5]

    return StressResult(
        scenario=scenario_name,
        portfolio_pnl=portfolio_pnl,
        portfolio_pct=portfolio_pct,
        positions=results,
        worst_positions=worst,
    )
