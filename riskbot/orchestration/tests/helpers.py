"""Test helpers: a run service wired entirely from ``contract.fakes``, stubs and polling."""

from __future__ import annotations

import re
import time
from typing import Any

from riskbot.contract import catalog, fakes
from riskbot.contract.types import (
    QuestionId,
    RunRecord,
    RunStatus,
    VariationResult,
    VerifierFinding,
)
from riskbot.orchestration import run_service


class RaisingModel:
    """Wraps a fake model and raises for parameter combinations selected by ``when``."""

    def __init__(self, spec, when=lambda params: True) -> None:
        self.spec = spec
        self._inner = fakes.FakeModel(spec)
        self._when = when

    def run(self, dataset, params, seed):
        if self._when(params):
            raise RuntimeError(f"boom for {params}")
        return self._inner.run(dataset, params, seed)


class NumberFlaggingVerifier(fakes.FakeVerifier):
    """Verifier stub: every number in the text must be in ``allowed`` (FakeVerifier accepts everything)."""

    def __init__(self, allowed: set[float]) -> None:
        self.allowed = allowed

    def verify_text(self, location: str, text: str, results: list[VariationResult]) -> list[VerifierFinding]:
        out = []
        for m in re.finditer(r"-?\d+(?:\.\d+)?", text):
            v = float(m.group())
            ok = v in self.allowed
            out.append(VerifierFinding(location=location, text=m.group(), value=v, matched=ok,
                                       message="matched" if ok else "number not found in any metric"))
        return out


#: Services created by ``make_service``; closed after each test by the autouse fixture in conftest.
CREATED: list[Any] = []


def make_service(*, registry=None, store=None, verifier=None, drafter=None, checkpoint_path=":memory:",
                 **overrides: Any):
    registry = registry or fakes.FakeRegistry()
    kwargs = dict(
        registry=registry, planner=fakes.FakePlanner(), executor=fakes.FakeExecutor(registry),
        comparator=fakes.FakeComparator(), verifier=verifier or fakes.FakeVerifier(),
        store=store if store is not None else fakes.FakeStore(), reporter=fakes.FakeReporter(),
        assessor=fakes.FakeAssessor(),
        samples={q: (lambda q=q: fakes.fake_dataset(q)) for q in QuestionId},
        drafter=drafter, checkpoint_path=checkpoint_path,
    )
    kwargs.update(overrides)
    svc = run_service(**kwargs)
    CREATED.append(svc)
    return svc


def registry_with(model_id: str, when=lambda params: True) -> fakes.FakeRegistry:
    """Fake registry where ``model_id`` raises for parameter sets matching ``when``."""
    models = [RaisingModel(s, when) if s.model_id == model_id else fakes.FakeModel(s)
              for s in catalog.MODEL_SPECS.values()]
    return fakes.FakeRegistry(models)


def poll(svc, run_id: str, until=(RunStatus.AWAITING_REVIEW, RunStatus.FAILED), timeout: float = 30.0) -> RunRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = svc.get_run(run_id)
        if rec.status in until:
            return rec
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} still {svc.get_run(run_id).status} after {timeout}s")
