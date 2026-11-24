"""Variation planner (``ports.VariationPlanner``): turns a ``QuestionPlan`` into concrete ``VariationSpec``s.

Algorithm
---------
1. Validate that ``plan.grid.model_id`` and every extra's ``model_id`` exist in ``catalog.MODEL_SPECS``
   (the catalogue, not a registry: plans are validated against the contract, independent of wiring).
2. Enumerate the cartesian product of ``grid.dimensions`` in the order the dimensions and their values
   are listed (``itertools.product``: the last dimension varies fastest). For each combination,
   ``conformance.resolve_params(spec, {**fixed, **combo})`` (a varied value overrides a fixed one) applies defaults, validates types, choices and
   ranges (``ValidationFailed`` propagates) and drops parameters whose ``applies_when`` is not met.
3. ``variation_id(model_id, effective_params)``; a combination whose effective parameters were already seen
   is dropped (first occurrence wins), so e.g. ``covariance`` collapses for the historical methods.
4. ``seed = derive_seed(run_seed, variation_id)``: independent of execution order.
5. If the number of distinct grid variations exceeds ``min(plan.max_variations, LIMITS["max_variations"])``
   raise ``LimitExceeded``.
6. Extras are appended in plan order the same way (``role="extra"``, de-duplicated by variation id).

The output is fully deterministic: the same plan and seed give the same list in the same order.

A guard also rejects (``LimitExceeded``) a raw cartesian product larger than ``RAW_PRODUCT_FACTOR`` times
the limit before enumerating it, so a malicious plan cannot make the planner spin.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.errors import LimitExceeded, ValidationFailed
from riskbot.contract.hashing import derive_seed, variation_id
from riskbot.contract.types import ModelSpec, QuestionPlan, VariationSpec

RAW_PRODUCT_FACTOR = 50


def _catalog_spec(model_id: str, where: str) -> ModelSpec:
    try:
        return catalog.MODEL_SPECS[model_id]
    except KeyError:
        raise ValidationFailed(f"{where}: unknown model {model_id!r} (not in the catalogue)", model_id=model_id) from None


class GridPlanner:
    """Deterministic grid expansion with ``applies_when`` de-duplication."""

    def expand(self, plan: QuestionPlan, seed: int) -> list[VariationSpec]:
        """Return grid variations (role='grid') followed by extras (role='extra'). See the module docstring."""
        grid_spec = _catalog_spec(plan.grid.model_id, "grid")
        if grid_spec.question != plan.question:
            raise ValidationFailed(
                f"grid model {grid_spec.model_id!r} belongs to {grid_spec.question.value}, not {plan.question.value}"
            )
        extra_specs = [_catalog_spec(e.model_id, f"extras[{i}]") for i, e in enumerate(plan.extras)]
        limit = min(plan.max_variations, catalog.LIMITS["max_variations"])

        dims = plan.grid.dimensions
        for name, values in dims.items():
            if not values:
                raise ValidationFailed(f"grid dimension {name!r} has no values", param=name)
        raw = math.prod(len(v) for v in dims.values())
        if raw > limit * RAW_PRODUCT_FACTOR:
            raise LimitExceeded(f"grid has {raw} raw combinations; limit is {limit} variations", limit=limit)

        out: list[VariationSpec] = []
        seen: set[str] = set()
        names = list(dims)
        for combo in itertools.product(*dims.values()):
            params: dict[str, Any] = {**plan.grid.fixed, **dict(zip(names, combo))}
            vs = self._make(plan, grid_spec, params, seed, "grid", seen)
            if vs is not None:
                out.append(vs)
        if len(out) > limit:
            raise LimitExceeded(
                f"plan expands to {len(out)} distinct grid variations; limit is {limit}",
                n_variations=len(out), limit=limit,
            )
        for extra, spec in zip(plan.extras, extra_specs):
            vs = self._make(plan, spec, dict(extra.params), seed, "extra", seen)
            if vs is not None:
                out.append(vs)
        return out

    @staticmethod
    def _make(plan: QuestionPlan, spec: ModelSpec, params: dict[str, Any], seed: int, role: str,
              seen: set[str]) -> VariationSpec | None:
        effective = resolve_params(spec, params)
        vid = variation_id(spec.model_id, effective)
        if vid in seen:
            return None
        seen.add(vid)
        return VariationSpec(variation_id=vid, question=plan.question, model_id=spec.model_id, params=effective,
                             seed=derive_seed(seed, vid), role=role)
