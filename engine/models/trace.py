"""Math traces: the step-by-step working behind a model result, for analysts to check.

A ``Trace`` records the formula (LaTeX), the substituted numbers and the value of every step,
together with the inputs, the assumptions and a hash of the inputs so the run can be reproduced.
Traces are produced by the deterministic ``models.explain`` functions; nothing in a trace comes
from a language model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

TRACE_SCHEMA_VERSION = "1"


@dataclass
class TraceStep:
    id: str
    title: str
    formula: str  # LaTeX, no surrounding $ delimiters
    substitution: str  # the same formula with the numbers filled in (plain text or LaTeX)
    value: float | None = None
    unit: str = ""
    table: list[dict[str, Any]] | None = None  # per-asset detail for vector-valued steps
    note: str = ""


@dataclass
class Trace:
    trace_id: str
    model: str
    inputs: dict[str, Any]
    assumptions: list[str]
    steps: list[TraceStep]
    result: dict[str, float]
    input_hash: str
    warnings: list[str] = field(default_factory=list)
    schema_version: str = TRACE_SCHEMA_VERSION

    def step(self, step_id: str) -> TraceStep:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [f"# {self.model}  ·  `{self.trace_id}`", ""]
        if self.warnings:
            lines += [f"> **Warning:** {w}" for w in self.warnings] + [""]
        lines += ["## Assumptions", *[f"- {a}" for a in self.assumptions], "", "## Steps", ""]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"**{i}. {s.title}**  (`{s.id}`)")
            lines.append(f"$${s.formula}$$")
            lines.append(f"{s.substitution}")
            if s.value is not None:
                lines.append(f"= **{s.value:.6g}** {s.unit}".rstrip())
            if s.table:
                cols = list(s.table[0])
                lines.append("")
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("|" + "---|" * len(cols))
                for row in s.table:
                    lines.append("| " + " | ".join(_fmt(row[c]) for c in cols) + " |")
            if s.note:
                lines.append(f"*{s.note}*")
            lines.append("")
        lines += ["## Result", *[f"- {k}: {v:.6g}" for k, v in self.result.items()], "",
                  f"Input hash: `{self.input_hash}`"]
        return "\n".join(lines)


def _fmt(v: Any) -> str:
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def input_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON-serialisable payload (keys sorted, floats via repr)."""
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def make_trace_id(model: str, digest: str) -> str:
    return f"{model}-{digest[:10]}"
