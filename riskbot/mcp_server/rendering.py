"""Markdown rendering of contract objects for MCP resources.

A ``Trace`` is the step-by-step working behind every number Riskbot produces. MCP clients (Claude
Desktop, Claude Code) display resources as text, so traces are rendered as Markdown with display
maths (``$$...$$``) that renderers such as KaTeX or MathJax understand:

* title, model id and trace id;
* assumptions (bullets) and the input summary;
* numbered steps, each with the LaTeX formula, the substitution, the value with its unit,
  an optional per-row table (as a Markdown table) and a note;
* final results, warnings and the input hash that makes the trace reproducible.

Rendering is pure and deterministic: the same trace always gives the same text.
"""

from __future__ import annotations

import json
import math
from typing import Any

from riskbot.contract.types import TableCell, Trace, TraceStep, Unit

__all__ = ["format_number", "render_trace", "render_table"]


def format_number(value: float | int | None) -> str:
    """Format a number faithfully for display.

    Uses up to 10 significant digits (``format(v, '.10g')``) so that the printed value matches the
    trace value closely enough for a number verifier, without float noise such as ``0.30000000000000004``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return str(value)
    return format(value, ".10g")


def _cell(value: TableCell) -> str:
    """One table cell: numbers formatted, strings escaped for Markdown tables."""
    if value is None:
        return ""
    if isinstance(value, (bool, int, float)):
        return format_number(value)
    return str(value).replace("|", r"\|").replace("\n", " ")


def render_table(rows: list[dict[str, TableCell]]) -> str:
    """Render a list of row dicts as a Markdown table.

    Columns are the union of the row keys in first-seen order; missing cells are left empty.
    """
    if not rows:
        return "_(empty table)_"
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    header = "| " + " | ".join(_cell(c) for c in columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_cell(row.get(c)) for c in columns) + " |" for row in rows]
    return "\n".join([header, rule, *body])


def _unit(unit: Unit | None) -> str:
    return f" {unit.value}" if unit is not None else ""


def _render_step(index: int, step: TraceStep) -> list[str]:
    lines = [f"### {index}. {step.title}", "", f"Step id: `{step.id}`", ""]
    formula = step.formula.strip()
    if formula:
        lines += ["$$", formula, "$$", ""]
    if step.substitution.strip():
        lines += [f"**Substitution:** {step.substitution.strip()}", ""]
    if step.value is not None:
        lines += [f"**Value:** {format_number(step.value)}{_unit(step.unit)}", ""]
    if step.table:
        lines += [render_table(step.table), ""]
    if step.note.strip():
        lines += [f"_Note:_ {step.note.strip()}", ""]
    return lines


def _json_inline(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def render_trace(trace: Trace) -> str:
    """Render a trace as a self-contained Markdown document."""
    lines: list[str] = [
        f"# {trace.title}",
        "",
        f"- Trace id: `{trace.trace_id}`",
        f"- Model: `{trace.model_id}`",
        "",
        "## Assumptions",
        "",
    ]
    lines += [f"- {a}" for a in trace.assumptions] or ["- (none stated)"]
    lines.append("")
    if trace.inputs:
        lines += ["## Inputs", ""]
        lines += [f"- `{k}`: `{_json_inline(v)}`" for k, v in trace.inputs.items()]
        lines.append("")
    lines += ["## Steps", ""]
    for i, step in enumerate(trace.steps, start=1):
        lines += _render_step(i, step)
    if trace.result:
        lines += ["## Result", "", "| Name | Value |", "| --- | --- |"]
        lines += [f"| `{k}` | {format_number(v)} |" for k, v in trace.result.items()]
        lines.append("")
    lines += ["## Warnings", ""]
    lines += [f"- {w}" for w in trace.warnings] or ["- None."]
    lines += ["", "## Input hash", "", f"`{trace.input_hash}`", ""]
    return "\n".join(lines)
