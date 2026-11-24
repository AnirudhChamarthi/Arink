"""Enforcement of ``catalog.LIMITS`` at the MCP boundary.

The contract (CONTRACT.md section 3, ``catalog.LIMITS``) says every entry point validates the hard
limits before work starts; services re-check. Checking here gives an agent a fast, explicit
``limit_exceeded`` tool error instead of a long-running call that fails later.

Limits checked
--------------
* ``max_positions``           - market dataset positions.
* ``max_history_days``        - market dataset return-history length (``dates``).
* ``max_balance_sheet_items`` - assets + loan pools + deposit segments + wholesale lines + hedges.
* ``max_holdings``            - climate portfolio holdings.
* ``max_variations``          - size of a plan: cartesian product of grid dimensions plus extras.
  This is an upper bound (the planner may collapse duplicates), so a plan rejected here is
  certainly over the planner's own limit or at the edge of it.
"""

from __future__ import annotations

import math

from riskbot.contract import catalog
from riskbot.contract.errors import LimitExceeded
from riskbot.contract.types import BankBalanceSheet, ClimatePortfolio, Dataset, MarketDataset, QuestionPlan

__all__ = ["check_dataset", "check_plan", "plan_size"]


def _check(name: str, actual: int, what: str) -> None:
    limit = catalog.LIMITS[name]
    if actual > limit:
        raise LimitExceeded(f"{what} {actual} exceeds {name}={limit}", limit=name, actual=actual, maximum=limit)


def check_dataset(dataset: Dataset) -> None:
    """Raise ``LimitExceeded`` if the dataset is larger than ``catalog.LIMITS`` allows."""
    if isinstance(dataset, MarketDataset):
        _check("max_positions", len(dataset.positions), "positions")
        _check("max_history_days", len(dataset.dates), "history days")
    elif isinstance(dataset, BankBalanceSheet):
        items = (len(dataset.assets) + len(dataset.loan_pools) + len(dataset.deposits)
                 + len(dataset.wholesale_funding) + len(dataset.hedges))
        _check("max_balance_sheet_items", items, "balance-sheet items")
    elif isinstance(dataset, ClimatePortfolio):
        _check("max_holdings", len(dataset.holdings), "holdings")


def plan_size(plan: QuestionPlan) -> int:
    """Upper bound on the number of variations: product of dimension lengths plus extras."""
    grid = math.prod(len(v) for v in plan.grid.dimensions.values()) if plan.grid.dimensions else 1
    return grid + len(plan.extras)


def check_plan(plan: QuestionPlan) -> None:
    """Raise ``LimitExceeded`` if the plan would expand beyond ``catalog.LIMITS['max_variations']``."""
    _check("max_variations", plan_size(plan), "planned variations")
