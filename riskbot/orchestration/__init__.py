"""Riskbot v2 orchestration: the ``RunService`` implementation on a LangGraph state machine.

Entry point (contract section 2)::

    run_service(*, registry, planner, executor, comparator, verifier, store, reporter, assessor,
                samples, drafter=None, checkpoint_path=":memory:") -> RunService

See ``README.md`` in this package for the graph, state schema, node contracts, threading and failure
semantics.
"""

from __future__ import annotations

from typing import Callable

from riskbot.contract import ports
from riskbot.contract.types import Dataset, QuestionId

from .drafting import ScriptedDrafter
from .graph import RunState
from .service import OrchestratedRunService


def run_service(
    *,
    registry: ports.ModelRegistry,
    planner: ports.VariationPlanner,
    executor: ports.VariationExecutor,
    comparator: ports.Comparator,
    verifier: ports.NumberVerifier,
    store: ports.RunStore,
    reporter: ports.Reporter,
    assessor: ports.Assessor,
    samples: dict[QuestionId, Callable[[], Dataset]],
    drafter: ports.RationaleDrafter | None = None,
    checkpoint_path: str = ":memory:",
) -> OrchestratedRunService:
    """Build the ``RunService``. ``drafter=None`` disables the LLM path; ``checkpoint_path`` is the SQLite
    file for LangGraph checkpoints (``":memory:"`` for a single process; a file lets another instance that
    shares the same ``store`` resume runs awaiting review)."""
    return OrchestratedRunService(
        registry=registry, planner=planner, executor=executor, comparator=comparator, verifier=verifier,
        store=store, reporter=reporter, assessor=assessor, samples=samples, drafter=drafter,
        checkpoint_path=checkpoint_path,
    )


__all__ = ["OrchestratedRunService", "RunState", "ScriptedDrafter", "run_service"]
