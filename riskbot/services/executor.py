"""Variation executor (``ports.VariationExecutor``): runs one variation and never raises for model errors.

Behaviour
---------
* Looks the model up in the registry, runs ``model.run(dataset, spec.params, spec.seed)`` and times the
  call with ``time.perf_counter`` (``duration_ms``; includes the lookup and the conformance check).
* Any exception (including ``NotFound`` for an unregistered model) becomes
  ``VariationResult.error = "<ExceptionType>: <message>"`` with ``output=None``.
* The output is checked with ``conformance.check_output`` against the catalogue spec (falling back to the
  model's own spec for ids outside the catalogue); violations become
  ``error = "ContractViolation: <v1>; <v2>; ..."`` and the output is discarded, so a non-conforming number
  can never reach the comparison or a report.
* ``execute_many`` runs a list of variations on a thread pool and returns results in input order.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from riskbot.contract import catalog
from riskbot.contract.conformance import check_output
from riskbot.contract.ports import ModelRegistry
from riskbot.contract.types import Dataset, VariationResult, VariationSpec


class ModelExecutor:
    """``VariationExecutor`` backed by a ``ModelRegistry``."""

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def execute(self, spec: VariationSpec, dataset: Dataset) -> VariationResult:
        """Run one variation; errors and contract violations are captured in ``VariationResult.error``."""
        start = time.perf_counter()
        try:
            model = self.registry.get(spec.model_id)
            output = model.run(dataset, dict(spec.params), spec.seed)
            model_spec = catalog.MODEL_SPECS.get(spec.model_id, model.spec)
            violations = check_output(model_spec, output)
        except Exception as exc:  # noqa: BLE001 - captured by design, never crosses the boundary
            return VariationResult(spec=spec, error=f"{type(exc).__name__}: {exc}", duration_ms=_ms(start))
        if violations:
            return VariationResult(spec=spec, error="ContractViolation: " + "; ".join(violations),
                                   duration_ms=_ms(start))
        return VariationResult(spec=spec, output=output, duration_ms=_ms(start))

    def execute_many(self, specs: list[VariationSpec], dataset: Dataset, max_workers: int = 4) -> list[VariationResult]:
        """Execute ``specs`` concurrently (``max_workers`` threads); results keep the order of ``specs``."""
        if max_workers <= 1 or len(specs) <= 1:
            return [self.execute(s, dataset) for s in specs]
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="riskbot-exec") as pool:
            return list(pool.map(lambda s: self.execute(s, dataset), specs))


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
