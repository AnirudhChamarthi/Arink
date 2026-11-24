"""Reporter (``ports.Reporter``): deterministic Markdown report and verified headline sentences.

Headline rules
--------------
Headline sentences may contain only numbers that are metric values of the run's variations, so that
``NumberVerifier.verify_text`` matches every one of them:

* metric ranges cite ``MetricRange.min`` and ``.max`` only (real values; a median of an even number of
  values is an average that may match nothing, so medians are never cited);
* break-evens cite the break-even metric value itself;
* everything else (counts of variations, label counts, spreads, effects) is described in words.

As a safety net every candidate sentence is verified with ``TraceNumberVerifier`` and dropped if any of
its numbers does not match (this can only happen for unusual catalogue text containing digits).

Markdown sections (always in this order; empty sections say so): title (question title from
``catalog.QUESTIONS``), run metadata, synthetic-data banner, headline, metric ranges, method spread,
sensitivity, conclusion flips, break-evens, label counts, qualitative assessment (marked **Judgment**),
overrides, sign-off, variations. The output depends only on the inputs (no clock, no randomness).
"""

from __future__ import annotations

from riskbot.contract import catalog
from riskbot.contract.types import (
    Comparison,
    ModelSpec,
    Report,
    RunResult,
    SignOff,
    Unit,
)

from .formatting import format_difference, format_value, md_cell
from .verifier import TraceNumberVerifier, extract_numbers

_SYNTHETIC = ("The dataset is synthetic sample data: the figures illustrate the method and describe no real "
              "portfolio or institution.")


def _no_digits(text: str) -> bool:
    return not any(c.isdigit() for c in text)


class MarkdownReporter:
    """Builds a ``Report`` from a ``RunResult``; see the module docstring."""

    def __init__(self) -> None:
        self._verifier = TraceNumberVerifier()

    # -- headline -------------------------------------------------------------------------------
    @staticmethod
    def headline_metrics(spec: ModelSpec | None, comparison: Comparison, n: int = 2) -> list[str]:
        """First ``n`` non-optional metrics with ``higher_is_worse`` set, non-currency ones first."""
        if spec is None:
            return list(comparison.metric_ranges)[:n]
        keys = [m for m in spec.metrics if not m.optional and m.higher_is_worse is not None
                and m.key in comparison.metric_ranges]
        keys.sort(key=lambda m: m.unit == Unit.CURRENCY)  # stable: catalogue order within each group
        return [m.key for m in keys[:n]]

    def headline(self, result: RunResult) -> list[str]:
        """Verified headline sentences (see module docstring)."""
        run, comp, plan = result.run, result.comparison, result.plan
        spec = catalog.MODEL_SPECS.get(plan.grid.model_id)
        descs = {m.key: m.description.rstrip(".") for m in spec.metrics} if spec else {}
        out: list[str] = []
        if run.synthetic:
            out.append(_SYNTHETIC)

        grid = [v for v in result.variations if v.spec.role == "grid"]
        ok_grid = [v for v in grid if v.output is not None and not v.error]
        failed = [v for v in result.variations if v.output is None or v.error]
        if not ok_grid:
            out.append("No grid variation completed successfully, so no figures are reported.")
        elif failed:
            out.append("Some variations failed and are excluded from the comparison (see Variations).")
        else:
            out.append("Every planned variation completed and passed the output conformance checks.")

        for key in self.headline_metrics(spec, comp):
            r = comp.metric_ranges[key]
            desc = descs.get(key, "")
            name = f"{desc} (`{key}`)" if desc and _no_digits(desc) else f"`{key}`"
            lo, hi = format_value(r.min, r.unit), format_value(r.max, r.unit)
            if lo == hi:
                out.append(f"{name} is {lo} in every successful grid variation.")
            else:
                out.append(f"Across the successful grid variations, {name} ranges from {lo} to {hi}.")

        if spec and spec.method_param and spec.method_param in plan.grid.dimensions:
            keys = self.headline_metrics(spec, comp, 1)
            row = next((s for s in comp.sensitivity if s.dimension == spec.method_param and keys
                        and s.metric == keys[0]), None)
            if row and len(row.medians) >= 2 and row.effect > 0:
                hi_m = max(row.medians, key=lambda k: row.medians[k])
                lo_m = min(row.medians, key=lambda k: row.medians[k])
                out.append(f"Method choice matters: the median `{row.metric}` is highest with "
                           f"{spec.method_param} `{hi_m}` and lowest with `{lo_m}` (see Method spread).")

        if spec and spec.pass_label and spec.pass_label in comp.label_counts:
            counts = comp.label_counts[spec.pass_label]
            p, f = counts.get("pass", 0), counts.get("fail", 0)
            if p and f:
                verdict = "mixed: some grid variations pass and some fail"
            elif p:
                verdict = "pass in every grid variation that produced a verdict"
            elif f:
                verdict = "fail in every grid variation that produced a verdict"
            else:
                verdict = "not available for any grid variation"
            out.append(f"The `{spec.pass_label}` outcome is {verdict}.")
            dims = list(dict.fromkeys(fl.dimension for fl in comp.flips))
            if dims:
                out.append(f"The `{spec.pass_label}` conclusion flips with " + ", ".join(f"`{d}`" for d in dims)
                           + " (see Conclusion flips).")

        for be in comp.break_evens:
            plain = not extract_numbers(be.description)  # descriptions may quote numeric parameters
            if be.found and be.value is not None:
                ctx = f" ({be.description.rstrip('.')})" if plain else ""
                out.append(f"Reverse stress: `{be.name}` is {format_value(be.value, be.unit)}{ctx}.")
            else:
                ctx = f": {be.description.rstrip('.')}" if plain else " within the search range"
                out.append(f"Reverse stress, `{be.name}`{ctx}." if plain
                           else f"Reverse stress: no breach found for `{be.name}`{ctx}.")

        out.append(f"Qualitative assessment (judgment, not calculation): overall residual rating "
                   f"{result.assessment.overall.value}.")
        return [s for s in out
                if all(f.matched for f in self._verifier.verify_text("headline", s, result.variations))]

    # -- report ---------------------------------------------------------------------------------
    def build(self, result: RunResult, signoff: SignOff | None) -> Report:
        headline = self.headline(result)
        return Report(run=result.run, headline=headline, comparison=result.comparison,
                      assessment=result.assessment, signoff=signoff,
                      markdown=self.markdown(result, signoff, headline))

    def markdown(self, result: RunResult, signoff: SignOff | None, headline: list[str]) -> str:
        run, comp, a = result.run, result.comparison, result.assessment
        q = catalog.QUESTIONS.get(run.question)
        L: list[str] = [f"# {q.title if q else run.question.value}", ""]

        L += ["## Run", "", "| Field | Value |", "|---|---|"]
        for k, v in [("Run id", run.run_id), ("Question", run.question.value), ("Status", run.status.value),
                     ("Dataset", run.dataset_name), ("Synthetic data", "yes" if run.synthetic else "no"),
                     ("Created (UTC)", run.created_at.isoformat()), ("Updated (UTC)", run.updated_at.isoformat()),
                     ("Grid model", result.plan.grid.model_id), ("Variations", run.n_variations),
                     ("Input hash", f"`{run.input_hash}`"), ("Contract version", run.contract_version)]:
            L.append(f"| {k} | {md_cell(v)} |")
        if run.error:
            L.append(f"| Error | {md_cell(run.error)} |")
        L.append("")
        if run.synthetic:
            L += [f"> **SYNTHETIC DATA.** {_SYNTHETIC}", ""]

        L += ["## Headline", ""] + [f"- {s}" for s in headline] + [""]
        L += ["*Every number in the headline is a metric value from the run, verified against its trace.*", ""]

        L += ["## Metric ranges (successful grid variations)", ""]
        if comp.metric_ranges:
            L += ["| Metric | Unit | Min | Median | Max | n |", "|---|---|---:|---:|---:|---:|"]
            for k, r in comp.metric_ranges.items():
                L.append(f"| `{k}` | {r.unit.value} | {format_value(r.min, r.unit)} | {format_value(r.median, r.unit)}"
                         f" | {format_value(r.max, r.unit)} | {r.n} |")
        else:
            L.append("No successful grid variations.")
        L.append("")

        spec = catalog.MODEL_SPECS.get(result.plan.grid.model_id)
        mp = spec.method_param if spec else None
        L += ["## Method spread", ""]
        if comp.method_spread:
            L += [f"Ratio of the highest to the lowest per-method median across `{mp}` (positive values only).", "",
                  "| Metric | Max / min |", "|---|---:|"]
            L += [f"| `{k}` | {v:.2f}x |" for k, v in comp.method_spread.items()]
        else:
            L.append("Not applicable (no method parameter varied, or fewer than two positive method medians).")
        L.append("")

        L += ["## Sensitivity", ""]
        if comp.sensitivity:
            L += ["Median of each metric per value of one dimension; effect = max - min of those medians.", "",
                  "| Dimension | Metric | Medians by value | Effect |", "|---|---|---|---:|"]
            for s in comp.sensitivity:
                unit = comp.metric_ranges[s.metric].unit if s.metric in comp.metric_ranges else Unit.RATIO
                meds = "; ".join(f"{v}: {format_value(x, unit)}" for v, x in s.medians.items())
                L.append(f"| `{s.dimension}` | `{s.metric}` | {md_cell(meds)} | {format_difference(s.effect, unit)} |")
        else:
            L.append("No sensitivity rows.")
        L.append("")

        L += ["## Conclusion flips", ""]
        if comp.flips:
            L += ["| Label | Dimension | From | To | Outcome | Context |", "|---|---|---|---|---|---|"]
            for fl in comp.flips:
                L.append(f"| `{fl.label}` | `{fl.dimension}` | {md_cell(fl.from_value)} | {md_cell(fl.to_value)} | "
                         f"{fl.outcome_from} -> {fl.outcome_to} | {md_cell(fl.description)} |")
        else:
            L.append("No conclusion flips: changing one dimension at a time never changed the pass/fail outcome."
                     if spec and spec.pass_label else "Not applicable (the grid model has no pass/fail label).")
        L.append("")

        L += ["## Break-evens (reverse stress)", ""]
        if comp.break_evens:
            L += ["| Break-even | Found | Value | Trace | Description |", "|---|---|---:|---|---|"]
            for be in comp.break_evens:
                val = format_value(be.value, be.unit) if be.value is not None else "-"
                L.append(f"| `{be.name}` | {'yes' if be.found else 'no'} | {val} | "
                         f"{'`' + be.trace_id + '`' if be.trace_id else '-'} | {md_cell(be.description)} |")
        else:
            L.append("None in this plan.")
        L.append("")

        L += ["## Label counts (grid variations)", ""]
        if comp.label_counts:
            L += ["| Label | Counts |", "|---|---|"]
            for label, counts in comp.label_counts.items():
                L.append(f"| `{label}` | {md_cell(', '.join(f'{v}: {c}' for v, c in counts.items()))} |")
        else:
            L.append("No labels.")
        L.append("")

        L += ["## Qualitative assessment (Judgment)", "",
              "> **Judgment, not calculation.** Ratings below are qualitative, derived with the shared rating "
              "rules and reviewable by an analyst.", "",
              f"Overall residual rating: **{a.overall.value}**", "", f"Method: {a.method_note}", "",
              "| Factor | Likelihood | Impact | Control | Inherent | Residual | Source | Rationale | Evidence |",
              "|---|---:|---:|---|---|---|---|---|---|"]
        for f in a.factors:
            ev = "; ".join(f"{e.kind}:{e.ref}" for e in f.evidence) or "-"
            L.append(f"| {md_cell(f.name)} (`{f.factor_id}`) | {f.likelihood} | {f.impact} | {f.control.value} | "
                     f"{f.inherent.value} | {f.residual.value} | {f.source.value} | {md_cell(f.rationale)} | "
                     f"{md_cell(ev)} |")
        L.append("")

        L += ["## Overrides", ""]
        if a.overrides:
            L += ["| Factor | Field | Old | New | Reason | By | At (UTC) |", "|---|---|---|---|---|---|---|"]
            for o in a.overrides:
                L.append(f"| `{o.factor_id}` | {o.field} | {md_cell(o.old)} | {md_cell(o.new)} | {md_cell(o.reason)} "
                         f"| {md_cell(o.by)} | {o.at.isoformat()} |")
        else:
            L.append("No analyst overrides.")
        L.append("")

        L += ["## Sign-off", ""]
        if signoff:
            L += [f"- Decision: **{signoff.decision.value}**", f"- Reviewer: {signoff.reviewer}",
                  f"- At (UTC): {signoff.at.isoformat()}", f"- Comment: {signoff.comment or '-'}"]
        else:
            L.append("Not signed off yet.")
        L.append("")

        L += ["## Variations", "", "| Variation | Role | Model | Parameters | Result |", "|---|---|---|---|---|"]
        for v in result.variations:
            params = ", ".join(f"{k}={val}" for k, val in v.spec.params.items())
            status = "ok" if v.output is not None and not v.error else f"error: {v.error}"
            L.append(f"| `{v.spec.variation_id}` | {v.spec.role} | `{v.spec.model_id}` | {md_cell(params)} | "
                     f"{md_cell(status)} |")
        L.append("")
        return "\n".join(L)
