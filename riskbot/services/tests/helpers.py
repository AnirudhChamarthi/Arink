"""Builders for hand-made variation results used across the services tests."""

from __future__ import annotations

from typing import Any

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import derive_seed, model_input_hash, variation_id
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import ModelOutput, Unit, VariationResult, VariationSpec


def make_result(model_id: str, params: dict[str, Any], metrics: dict[str, float], labels: dict[str, str] | None = None,
                role: str = "grid", resolve: bool = True, units: dict[str, Unit] | None = None) -> VariationResult:
    """A successful VariationResult whose metrics link to trace steps of equal value."""
    spec = catalog.MODEL_SPECS[model_id]
    eff = resolve_params(spec, params) if resolve else dict(params)
    declared = {m.key: m.unit for m in spec.metrics}
    units = {**declared, **(units or {})}
    h = model_input_hash(model_id, {"test": True}, eff, 0)
    tb = TraceBuilder(model_id, "test", h, assumptions=[])
    ms = {}
    for k, v in metrics.items():
        tb.step(k, k, "x", str(v), value=v, unit=units[k])
        ms[k] = tb.metric(k, v, units[k])
    vid = variation_id(model_id, eff)
    out = ModelOutput(model_id=model_id, params=eff, metrics=ms, labels=labels or {}, traces=[tb.build(metrics)])
    vs = VariationSpec(variation_id=vid, question=spec.question, model_id=model_id, params=eff,
                       seed=derive_seed(1, vid), role=role)
    return VariationResult(spec=vs, output=out, duration_ms=1.0)


def make_error(model_id: str, params: dict[str, Any], role: str = "grid") -> VariationResult:
    spec = catalog.MODEL_SPECS[model_id]
    eff = resolve_params(spec, params)
    vid = variation_id(model_id, eff)
    vs = VariationSpec(variation_id=vid, question=spec.question, model_id=model_id, params=eff,
                       seed=derive_seed(1, vid), role=role)
    return VariationResult(spec=vs, error="RuntimeError: boom", duration_ms=1.0)
