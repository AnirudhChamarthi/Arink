"""Comparator (``ports.Comparator``): summarises a set of variation results into a ``Comparison``.

Only *successful* variations (``output`` present, ``error`` empty) are used. Grid variations
(``role="grid"``) feed ranges, spread, sensitivity, flips and label counts; extra runs feed break-evens.

metric_ranges
    For every metric present in any successful grid output (catalogue order first, then any other key
    sorted): min, ``statistics.median``, max and n.
method_spread
    If the grid model's spec has a ``method_param``: for each metric, the median per method value; with at
    least two *positive* per-method medians, spread = max / min of those medians. Metrics with fewer than
    two positive medians are omitted (a ratio of non-positive numbers is meaningless).
sensitivity
    For every grid dimension (plan order) x every non-optional catalogue metric with ``higher_is_worse``
    set: median of the metric per dimension value (keyed by ``str(effective value)``, first-seen order),
    effect = max - min of those medians. Variations where the dimension was dropped by ``applies_when``
    are skipped for that dimension; rows with no data are omitted.
flips
    For the spec's ``pass_label``: for each dimension, grid variations are grouped by *all other*
    effective parameters; every pair within a group whose label outcome differs (both outcomes in
    {pass, fail}) yields a ``ConclusionFlip`` from the earlier variation's value to the later one's.
    Order: dimension (plan order), group (first seen), pair (result order). Duplicates are removed and the
    list is capped at ``MAX_FLIPS`` (the first ones in that order).
break_evens
    For every successful extra run: each metric starting with ``breakeven_`` gives ``found=True``; each
    *optional* ``breakeven_`` metric of that model's spec that is absent gives ``found=False``,
    ``value=None``. The description names the extra's explicit parameters (e.g. ``target=capital``).
label_counts
    For every label of the grid outputs: every allowed value from the catalogue (zero counts included)
    plus any other observed value, in catalogue order.

Zero successful variations give an empty ``Comparison`` (no exception).
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.types import (
    BreakEven,
    Comparison,
    ConclusionFlip,
    MetricRange,
    ModelOutput,
    ModelSpec,
    QuestionPlan,
    SensitivityRow,
    VariationResult,
)

MAX_FLIPS = 50
_OUTCOMES = {"pass", "fail"}


def _ok(r: VariationResult) -> bool:
    return r.output is not None and not r.error


def _key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, default=str)


def _fmt_params(params: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items())


class StatisticalComparator:
    """Deterministic ``Comparator``; see the module docstring for every rule."""

    def compare(self, plan: QuestionPlan, results: list[VariationResult]) -> Comparison:
        ok = [r for r in results if _ok(r)]
        if not ok:
            return Comparison(question=plan.question, metric_ranges={})
        spec = catalog.MODEL_SPECS.get(plan.grid.model_id)
        grid = [r for r in ok if r.spec.role == "grid"]
        extras = [r for r in ok if r.spec.role == "extra"]
        return Comparison(
            question=plan.question,
            metric_ranges=self._ranges(spec, grid),
            method_spread=self._spread(spec, grid),
            sensitivity=self._sensitivity(plan, spec, grid),
            flips=self._flips(plan, spec, grid),
            break_evens=self._break_evens(plan, extras),
            label_counts=self._label_counts(spec, grid),
        )

    # -- ranges ---------------------------------------------------------------------------------
    @staticmethod
    def _metric_keys(spec: ModelSpec | None, outputs: list[ModelOutput]) -> list[str]:
        present = {k for o in outputs for k in o.metrics}
        declared = [m.key for m in spec.metrics] if spec else []
        return [k for k in declared if k in present] + sorted(present - set(declared))

    def _ranges(self, spec: ModelSpec | None, grid: list[VariationResult]) -> dict[str, MetricRange]:
        outputs = [r.output for r in grid]
        ranges: dict[str, MetricRange] = {}
        for key in self._metric_keys(spec, outputs):
            ms = [o.metrics[key] for o in outputs if key in o.metrics]
            vals = [m.value for m in ms]
            ranges[key] = MetricRange(unit=ms[0].unit, min=min(vals), median=statistics.median(vals),
                                      max=max(vals), n=len(vals))
        return ranges

    # -- method spread --------------------------------------------------------------------------
    def _spread(self, spec: ModelSpec | None, grid: list[VariationResult]) -> dict[str, float]:
        if spec is None or not spec.method_param:
            return {}
        mp = spec.method_param
        outputs = [r.output for r in grid]
        spread: dict[str, float] = {}
        for key in self._metric_keys(spec, outputs):
            by_method: dict[str, list[float]] = defaultdict(list)
            for r in grid:
                if mp in r.spec.params and key in r.output.metrics:
                    by_method[str(r.spec.params[mp])].append(r.output.metrics[key].value)
            medians = [m for m in (statistics.median(v) for v in by_method.values()) if m > 0]
            if len(medians) >= 2:
                spread[key] = max(medians) / min(medians)
        return spread

    # -- sensitivity ----------------------------------------------------------------------------
    @staticmethod
    def _sensitivity(plan: QuestionPlan, spec: ModelSpec | None, grid: list[VariationResult]) -> list[SensitivityRow]:
        if spec is None:
            return []
        metrics = [m.key for m in spec.metrics if not m.optional and m.higher_is_worse is not None]
        rows = []
        for dim in plan.grid.dimensions:
            for key in metrics:
                groups: dict[str, list[float]] = {}
                for r in grid:
                    if dim in r.spec.params and key in r.output.metrics:
                        groups.setdefault(str(r.spec.params[dim]), []).append(r.output.metrics[key].value)
                if not groups:
                    continue
                medians = {v: float(statistics.median(xs)) for v, xs in groups.items()}
                rows.append(SensitivityRow(dimension=dim, metric=key, medians=medians,
                                           effect=max(medians.values()) - min(medians.values())))
        return rows

    # -- flips ----------------------------------------------------------------------------------
    @staticmethod
    def _flips(plan: QuestionPlan, spec: ModelSpec | None, grid: list[VariationResult]) -> list[ConclusionFlip]:
        if spec is None or not spec.pass_label:
            return []
        label = spec.pass_label
        dims = list(plan.grid.dimensions)
        flips: list[ConclusionFlip] = []
        seen: set[tuple] = set()
        for dim in dims:
            groups: dict[str, list[VariationResult]] = {}
            for r in grid:
                if dim in r.spec.params and r.output.labels.get(label) in _OUTCOMES:
                    rest = {k: v for k, v in r.spec.params.items() if k != dim}
                    groups.setdefault(_key(rest), []).append(r)
            for gkey, members in groups.items():
                for i, a in enumerate(members):
                    for b in members[i + 1:]:
                        oa, ob = a.output.labels[label], b.output.labels[label]
                        va, vb = str(a.spec.params[dim]), str(b.spec.params[dim])
                        if oa == ob or va == vb:
                            continue
                        ident = (dim, gkey, va, vb)
                        if ident in seen:
                            continue
                        seen.add(ident)
                        context = {d: a.spec.params[d] for d in dims if d != dim and d in a.spec.params}
                        where = f" with {_fmt_params(context)}" if context else ""
                        flips.append(ConclusionFlip(
                            label=label, dimension=dim, from_value=va, to_value=vb, outcome_from=oa,
                            outcome_to=ob,
                            description=f"{label} changes from {oa} to {ob} when {dim} goes from {va} to {vb}{where}.",
                        ))
                        if len(flips) >= MAX_FLIPS:
                            return flips
        return flips

    # -- break-evens ----------------------------------------------------------------------------
    @staticmethod
    def _explicit_params(plan: QuestionPlan, r: VariationResult) -> dict[str, Any]:
        """The parameters the plan set explicitly for this extra run (falls back to all effective params)."""
        for extra in plan.extras:
            if extra.model_id != r.spec.model_id:
                continue
            spec = catalog.MODEL_SPECS.get(extra.model_id)
            try:
                eff = resolve_params(spec, extra.params) if spec else extra.params
            except Exception:  # noqa: BLE001 - an invalid extra simply does not match
                continue
            if eff == r.spec.params:
                return dict(extra.params)
        return dict(r.spec.params)

    def _break_evens(self, plan: QuestionPlan, extras: list[VariationResult]) -> list[BreakEven]:
        out: list[BreakEven] = []
        for r in extras:
            spec = catalog.MODEL_SPECS.get(r.spec.model_id)
            declared = {m.key: m for m in spec.metrics} if spec else {}
            params = self._explicit_params(plan, r)
            ctx = f"{r.spec.model_id} with {_fmt_params(params)}" if params else f"{r.spec.model_id} with default parameters"
            metrics = r.output.metrics
            keys = [k for k in declared if k in metrics] + sorted(set(metrics) - set(declared))
            for key in keys:
                if not key.startswith("breakeven_"):
                    continue
                m = metrics[key]
                what = declared[key].description.rstrip(".") if key in declared else key
                out.append(BreakEven(name=key, value=m.value, unit=m.unit, found=True, trace_id=m.trace_id,
                                     description=f"{what} ({ctx})."))
            for key, ms in declared.items():
                if key.startswith("breakeven_") and ms.optional and key not in metrics:
                    tid = r.output.traces[0].trace_id if r.output.traces else None
                    out.append(BreakEven(
                        name=key, value=None, unit=ms.unit, found=False, trace_id=tid,
                        description=f"{ms.description.rstrip('.')}: no breach within the search range ({ctx}).",
                    ))
        return out

    # -- label counts ---------------------------------------------------------------------------
    @staticmethod
    def _label_counts(spec: ModelSpec | None, grid: list[VariationResult]) -> dict[str, dict[str, int]]:
        observed: dict[str, dict[str, int]] = {}
        for r in grid:
            for label, value in r.output.labels.items():
                observed.setdefault(label, {}).setdefault(value, 0)
                observed[label][value] += 1
        declared = spec.labels if spec else {}
        order = [k for k in declared if k in observed] + sorted(set(observed) - set(declared))
        counts: dict[str, dict[str, int]] = {}
        for label in order:
            allowed = declared.get(label, [])
            row = {v: observed[label].get(v, 0) for v in allowed}
            row.update({v: c for v, c in sorted(observed[label].items()) if v not in row})
            counts[label] = row
        return counts
