"""TraceBuilder: the one way core models build traces and link metrics to steps.

Usage inside a model::

    tb = TraceBuilder(model_id, title, input_hash, assumptions=[...], inputs={...})
    tb.step("var", "Value at Risk", r"z_c\\sigma_p\\sqrt{h}", f"{z:.4f} x ...", value=var, unit=Unit.FRACTION_OF_GROSS)
    trace = tb.build(result={"var": var})
    metrics = {"var": tb.metric("var", var, Unit.FRACTION_OF_GROSS)}   # links to the step with id 'var'
"""

from __future__ import annotations

import math
from typing import Any

from .hashing import trace_id as make_trace_id
from .types import Metric, TableCell, Trace, TraceStep, Unit


class TraceBuilder:
    def __init__(
        self,
        model_id: str,
        title: str,
        input_hash: str,
        *,
        assumptions: list[str],
        inputs: dict[str, Any] | None = None,
        suffix: str = "",
    ) -> None:
        self.model_id = model_id
        self.title = title
        self.input_hash = input_hash
        self.assumptions = list(assumptions)
        self.inputs = dict(inputs or {})
        self.trace_id = make_trace_id(model_id, input_hash, suffix)
        self._steps: list[TraceStep] = []
        self._warnings: list[str] = []

    def step(
        self,
        step_id: str,
        title: str,
        formula: str,
        substitution: str,
        *,
        value: float | None = None,
        unit: Unit | None = None,
        table: list[dict[str, TableCell]] | None = None,
        note: str = "",
    ) -> TraceStep:
        if any(s.id == step_id for s in self._steps):
            raise ValueError(f"duplicate step id {step_id!r} in trace {self.trace_id}")
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"step {step_id!r} has a non-finite value")
        s = TraceStep(id=step_id, title=title, formula=formula, substitution=substitution,
                      value=value, unit=unit, table=table, note=note)
        self._steps.append(s)
        return s

    def warn(self, message: str) -> None:
        self._warnings.append(message)

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def metric(self, step_id: str, value: float, unit: Unit) -> Metric:
        """A metric linked to one of this trace's steps (the step must exist)."""
        if not any(s.id == step_id for s in self._steps):
            raise ValueError(f"metric refers to unknown step {step_id!r}")
        return Metric(value=float(value), unit=unit, trace_id=self.trace_id, trace_step=step_id)

    def build(self, result: dict[str, float]) -> Trace:
        return Trace(
            trace_id=self.trace_id, model_id=self.model_id, title=self.title, assumptions=self.assumptions,
            inputs=self.inputs, steps=list(self._steps), result={k: float(v) for k, v in result.items()},
            input_hash=self.input_hash, warnings=list(self._warnings),
        )
