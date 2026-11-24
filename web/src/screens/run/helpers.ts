import type { Metric, ModelSpec, VariationResult } from "../../api/types";

/** The metric of the first successful grid variation whose value equals `value` (to link min/max to a trace). */
export function findMetric(variations: VariationResult[], key: string, value: number): Metric | undefined {
  for (const v of variations) {
    if (v.spec.role !== "grid") continue;
    const m = v.output?.metrics[key];
    if (m && m.value === value) return m;
  }
  return undefined;
}

export function metricSpec(specs: ModelSpec[], key: string, modelId?: string): ModelSpec["metrics"][number] | undefined {
  const ordered = [...specs.filter((s) => s.model_id === modelId), ...specs.filter((s) => s.model_id !== modelId)];
  for (const s of ordered) {
    const m = s.metrics.find((x) => x.key === key);
    if (m) return m;
  }
  return undefined;
}
