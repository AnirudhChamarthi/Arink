"""The rubric tables: one tuple of ``FactorDef`` rows per question (factor ids as in CONTRACT.md section 8)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from riskbot.contract.types import QuestionId

from . import q1, q2, q3
from ._base import FactorDef

RUBRICS: Mapping[QuestionId, tuple[FactorDef, ...]] = MappingProxyType({
    QuestionId.Q1: q1.RUBRIC,
    QuestionId.Q2: q2.RUBRIC,
    QuestionId.Q3: q3.RUBRIC,
})

# The factor ids the contract requires, in contract order (checked by the tests).
CONTRACT_FACTOR_IDS: Mapping[QuestionId, tuple[str, ...]] = MappingProxyType({
    QuestionId.Q1: ("method_spread", "backtest_performance", "history_length", "data_quality", "concentration",
                    "short_exposure", "normality_reliance"),
    QuestionId.Q2: ("uninsured_deposits", "deposit_concentration", "duration_gap", "hedging", "htm_reliance",
                    "wholesale_dependence", "risk_governance", "credit_concentration"),
    QuestionId.Q3: ("emissions_coverage", "estimated_emissions", "scope3_coverage", "stale_data", "controversies",
                    "exclusion_breaches", "high_emitting_concentration", "scenario_dispersion"),
})
