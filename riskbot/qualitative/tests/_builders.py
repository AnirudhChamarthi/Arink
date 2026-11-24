"""Hand-built inputs for the qualitative tests: realistic ModelOutputs linked to traces."""

from __future__ import annotations

import re
import statistics
from typing import Any

from riskbot.contract import catalog
from riskbot.contract.hashing import sha256_hex, variation_id
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import (
    Comparison,
    ConclusionFlip,
    DataQualityFinding,
    MetricRange,
    ModelOutput,
    QuestionId,
    SensitivityRow,
    VariationResult,
    VariationSpec,
)


def output(model_id: str, metrics: dict[str, float], labels: dict[str, str] | None = None,
           params: dict[str, Any] | None = None, findings: list[DataQualityFinding] | None = None) -> ModelOutput:
    """A ModelOutput whose every metric links to a trace step with the same value."""
    spec = catalog.MODEL_SPECS[model_id]
    units = {m.key: m.unit for m in spec.metrics}
    params = dict(params or {})
    h = sha256_hex({"model_id": model_id, "params": params, "metrics": metrics})
    tb = TraceBuilder(model_id, spec.title, h, assumptions=["Test fixture."], inputs={"params": params})
    out = {}
    for key, value in metrics.items():
        tb.step(key, key, r"\text{fixture}", f"{value}", value=value, unit=units[key])
        out[key] = tb.metric(key, value, units[key])
    return ModelOutput(model_id=model_id, params=params, metrics=out, labels=dict(labels or {}),
                       traces=[tb.build({k: m.value for k, m in out.items()})], findings=list(findings or []))


def result(model_id: str, metrics: dict[str, float], labels: dict[str, str] | None = None,
           params: dict[str, Any] | None = None, role: str = "grid",
           findings: list[DataQualityFinding] | None = None) -> VariationResult:
    params = dict(params or {})
    spec = catalog.MODEL_SPECS[model_id]
    vid = variation_id(model_id, params)
    return VariationResult(
        spec=VariationSpec(variation_id=vid, question=spec.question, model_id=model_id, params=params, seed=1,
                           role=role),
        output=output(model_id, metrics, labels, params, findings), duration_ms=1.0)


def failed(model_id: str, params: dict[str, Any] | None = None, role: str = "grid") -> VariationResult:
    params = dict(params or {})
    spec = catalog.MODEL_SPECS[model_id]
    vid = variation_id(model_id, params)
    return VariationResult(
        spec=VariationSpec(variation_id=vid, question=spec.question, model_id=model_id, params=params, seed=1,
                           role=role),
        error="RuntimeError: model blew up", duration_ms=1.0)


def compare(question: QuestionId, results: list[VariationResult], flips: list[ConclusionFlip] | None = None,
            sensitivity: list[SensitivityRow] | None = None) -> Comparison:
    """A small comparator following CONTRACT.md 4.3 for ranges, method spread and label counts."""
    plan = catalog.DEFAULT_PLANS[question]
    spec = catalog.MODEL_SPECS[plan.grid.model_id]
    grid = [r for r in results if r.output and r.spec.role == "grid"]
    ranges: dict[str, MetricRange] = {}
    keys = sorted({k for r in grid for k in r.output.metrics})
    for k in keys:
        vals = sorted(r.output.metrics[k].value for r in grid if k in r.output.metrics)
        unit = next(r.output.metrics[k].unit for r in grid if k in r.output.metrics)
        ranges[k] = MetricRange(unit=unit, min=vals[0], median=statistics.median(vals), max=vals[-1], n=len(vals))
    spread: dict[str, float] = {}
    if spec.method_param:
        for k in keys:
            by: dict[str, list[float]] = {}
            for r in grid:
                if k in r.output.metrics and spec.method_param in r.spec.params:
                    by.setdefault(str(r.spec.params[spec.method_param]), []).append(r.output.metrics[k].value)
            meds = [statistics.median(v) for v in by.values()]
            meds = [m for m in meds if m > 0]
            if len(meds) >= 2:
                spread[k] = max(meds) / min(meds)
    counts: dict[str, dict[str, int]] = {}
    for r in grid:
        for lab, v in r.output.labels.items():
            counts.setdefault(lab, {})
            counts[lab][v] = counts[lab].get(v, 0) + 1
    return Comparison(question=question, metric_ranges=ranges, method_spread=spread, label_counts=counts,
                      flips=list(flips or []), sensitivity=list(sensitivity or []))


def finding(check: str, severity: str = "warning", field: str = "returns", subject: str | None = None) -> DataQualityFinding:
    return DataQualityFinding(check=check, severity=severity, field=field, subject=subject, count=1,
                              message=f"{check} detected.")


# ----------------------------------------------------------------------------------------------
# Checks used by several tests
# ----------------------------------------------------------------------------------------------

_PATH_PART = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?$")


def resolve_field(dataset: Any, path: str) -> Any:
    """Resolve 'positions[2].quantity' or 'governance.cro_vacancy_months' against a dataset."""
    obj = dataset
    for part in path.split("."):
        if isinstance(obj, dict):
            if part not in obj:
                raise KeyError(path)
            obj = obj[part]
            continue
        m = _PATH_PART.match(part)
        if not m:
            raise KeyError(path)
        obj = getattr(obj, m.group(1))
        if m.group(2) is not None:
            obj = obj[int(m.group(2))]
    return obj


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
