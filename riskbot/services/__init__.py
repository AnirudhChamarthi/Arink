"""Riskbot v2 services: registry, planner, executor, comparator, verifier, SQLite store and reporter.

Every factory returns a fresh object implementing the matching Protocol of ``riskbot.contract.ports``.
This package imports only ``riskbot.contract`` and the standard library. See ``README.md``.
"""

from __future__ import annotations

from riskbot.contract.ports import (
    Comparator,
    ModelRegistry,
    NumberVerifier,
    Reporter,
    RunStore,
    VariationExecutor,
    VariationPlanner,
)

from .comparator import StatisticalComparator
from .executor import ModelExecutor
from .planner import GridPlanner
from .registry import InMemoryRegistry
from .reporter import MarkdownReporter
from .store import SqliteRunStore
from .verifier import TraceNumberVerifier

__all__ = ["registry", "planner", "executor", "comparator", "verifier", "sqlite_store", "reporter",
           "InMemoryRegistry", "GridPlanner", "ModelExecutor", "StatisticalComparator", "TraceNumberVerifier",
           "SqliteRunStore", "MarkdownReporter"]


def registry() -> ModelRegistry:
    """An empty in-memory model registry."""
    return InMemoryRegistry()


def planner() -> VariationPlanner:
    """Grid planner with ``applies_when`` de-duplication and limit checks."""
    return GridPlanner()


def executor(registry: ModelRegistry) -> VariationExecutor:
    """Executor that runs models from ``registry`` and captures errors and contract violations.

    The returned object also offers ``execute_many(specs, dataset, max_workers=4)``.
    """
    return ModelExecutor(registry)


def comparator() -> Comparator:
    """Comparator producing ranges, method spread, sensitivity, flips, break-evens and label counts."""
    return StatisticalComparator()


def verifier() -> NumberVerifier:
    """Verifier of metric/trace equality and of numbers quoted in text."""
    return TraceNumberVerifier()


def sqlite_store(path: str) -> RunStore:
    """SQLite-backed run store at ``path`` (``":memory:"`` for an in-process database)."""
    return SqliteRunStore(path)


def reporter() -> Reporter:
    """Deterministic Markdown reporter with verified headline sentences."""
    return MarkdownReporter()
