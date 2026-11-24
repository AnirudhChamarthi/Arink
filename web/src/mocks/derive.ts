/**
 * Mock-only helpers. The contract fixtures come from fakes whose Comparator leaves sensitivity and label
 * counts empty; for a meaningful demo, mock mode derives them from the fixture variations using the
 * Comparator's documented rules (CONTRACT.md 4.3). The real API computes these server-side.
 */
import type { Comparison, ModelSpec, QuestionPlan, SensitivityRow, VariationResult } from "../api/types";

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

const key = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export function deriveComparison(comparison: Comparison, plan: QuestionPlan, variations: VariationResult[], spec?: ModelSpec): Comparison {
  const grid = variations.filter((v) => v.spec.role === "grid" && v.output);
  const out: Comparison = structuredClone(comparison);
  if (spec && out.sensitivity.length === 0) {
    const rows: SensitivityRow[] = [];
    for (const dim of Object.keys(plan.grid.dimensions)) {
      for (const m of spec.metrics) {
        if (m.optional || m.higher_is_worse === null) continue;
        const groups = new Map<string, number[]>();
        for (const v of grid) {
          if (!(dim in v.spec.params)) continue;
          const metric = v.output!.metrics[m.key];
          if (!metric) continue;
          const g = key(v.spec.params[dim]);
          groups.set(g, [...(groups.get(g) ?? []), metric.value]);
        }
        if (groups.size < 2) continue;
        const medians = Object.fromEntries([...groups].map(([g, xs]) => [g, median(xs)]));
        const vals = Object.values(medians);
        rows.push({ dimension: dim, metric: m.key, medians, effect: Math.max(...vals) - Math.min(...vals) });
      }
    }
    out.sensitivity = rows;
  }
  if (Object.keys(out.label_counts).length === 0) {
    const counts: Record<string, Record<string, number>> = {};
    for (const v of grid) {
      for (const [label, value] of Object.entries(v.output!.labels)) {
        counts[label] ??= {};
        counts[label][value] = (counts[label][value] ?? 0) + 1;
      }
    }
    out.label_counts = counts;
  }
  return out;
}
