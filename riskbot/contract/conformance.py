"""Shared validation of parameters and model outputs against the catalogue."""

from __future__ import annotations

import math
from typing import Any

from .errors import ValidationFailed
from .types import ModelOutput, ModelSpec, ParamSpec

_PY_TYPES = {"float": (int, float), "int": (int,), "str": (str,), "bool": (bool,)}


def _applies(p: ParamSpec, values: dict[str, Any]) -> bool:
    if not p.applies_when:
        return True
    return all(values.get(k) in allowed for k, allowed in p.applies_when.items())


def resolve_params(spec: ModelSpec, params: dict[str, Any] | None) -> dict[str, Any]:
    """Apply defaults, validate types/choices/ranges, reject unknown names, drop inapplicable parameters.

    Returns the effective parameters (inapplicable ones removed), which models put in ``ModelOutput.params``
    and the planner uses for variation ids.
    """
    params = dict(params or {})
    known = {p.name: p for p in spec.params}
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise ValidationFailed(f"unknown parameter(s) for {spec.model_id}: {unknown}", model_id=spec.model_id)
    values: dict[str, Any] = {}
    for p in spec.params:
        v = params.get(p.name, p.default)
        if p.type == "float" and isinstance(v, int) and not isinstance(v, bool):
            v = float(v)
        if v is None or isinstance(v, bool) and p.type != "bool" or not isinstance(v, _PY_TYPES[p.type]):
            raise ValidationFailed(f"{spec.model_id}.{p.name} must be {p.type}, got {v!r}", param=p.name)
        if p.type == "float" and not math.isfinite(v):
            raise ValidationFailed(f"{spec.model_id}.{p.name} must be finite", param=p.name)
        if p.choices is not None and v not in p.choices:
            raise ValidationFailed(f"{spec.model_id}.{p.name}={v!r} not in {p.choices}", param=p.name)
        if p.minimum is not None and v < p.minimum or p.maximum is not None and v > p.maximum:
            raise ValidationFailed(f"{spec.model_id}.{p.name}={v!r} outside [{p.minimum}, {p.maximum}]", param=p.name)
        values[p.name] = v
    return {k: v for k, v in values.items() if _applies(known[k], values)}


def check_output(spec: ModelSpec, output: ModelOutput) -> list[str]:
    """Return a list of contract violations (empty if the output conforms)."""
    problems: list[str] = []
    if output.model_id != spec.model_id:
        problems.append(f"model_id {output.model_id!r} != {spec.model_id!r}")
    declared = {m.key: m for m in spec.metrics}
    for key in sorted(set(output.metrics) - set(declared)):
        problems.append(f"undeclared metric {key!r}")
    for m in spec.metrics:
        if m.key not in output.metrics:
            if not m.optional:
                problems.append(f"missing metric {m.key!r}")
            continue
        got = output.metrics[m.key]
        if got.unit != m.unit:
            problems.append(f"metric {m.key!r} unit {got.unit.value} != {m.unit.value}")
        if not math.isfinite(got.value):
            problems.append(f"metric {m.key!r} is not finite")
    for label, allowed in spec.labels.items():
        if label not in output.labels:
            problems.append(f"missing label {label!r}")
        elif output.labels[label] not in allowed:
            problems.append(f"label {label!r}={output.labels[label]!r} not in {allowed}")
    for label in sorted(set(output.labels) - set(spec.labels)):
        problems.append(f"undeclared label {label!r}")
    steps = {(t.trace_id, s.id): s for t in output.traces for s in t.steps}
    for key, metric in output.metrics.items():
        if metric.trace_id is None or metric.trace_step is None:
            problems.append(f"metric {key!r} is not linked to a trace step")
        elif (metric.trace_id, metric.trace_step) not in steps:
            problems.append(f"metric {key!r} links to missing step {metric.trace_id}/{metric.trace_step}")
        else:
            sv = steps[(metric.trace_id, metric.trace_step)].value
            if sv is None or not math.isclose(sv, metric.value, rel_tol=1e-9, abs_tol=1e-12):
                problems.append(f"metric {key!r}={metric.value} differs from its trace step value {sv}")
    ids = [t.trace_id for t in output.traces]
    if len(ids) != len(set(ids)):
        problems.append("duplicate trace ids")
    return problems
