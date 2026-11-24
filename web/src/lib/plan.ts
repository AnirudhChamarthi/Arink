/**
 * Plan helpers: parameter validation and variation-count preview, mirroring
 * `conformance.resolve_params` and `ports.VariationPlanner.expand` on the server.
 */
import type { ModelSpec, ParamSpec, ParamValue, QuestionPlan } from "../api/types";

/** Python-style equality for parameter values (250 == 250.0; no bool/number mixing). */
function same(a: ParamValue | undefined, b: ParamValue | undefined): boolean {
  return a === b;
}

export function applies(p: ParamSpec, values: Record<string, ParamValue>): boolean {
  if (!p.applies_when) return true;
  return Object.entries(p.applies_when).every(([k, allowed]) => allowed.some((a) => same(a, values[k])));
}

/** Check one value against a parameter spec; returns a message or null. */
export function checkParamValue(p: ParamSpec, v: ParamValue | undefined): string | null {
  if (v === undefined || v === null || (typeof v === "number" && Number.isNaN(v))) return `${p.name}: a value is required`;
  switch (p.type) {
    case "bool":
      if (typeof v !== "boolean") return `${p.name} must be true or false`;
      break;
    case "int":
      if (typeof v !== "number" || !Number.isInteger(v)) return `${p.name} must be a whole number`;
      break;
    case "float":
      if (typeof v !== "number" || !Number.isFinite(v)) return `${p.name} must be a number`;
      break;
    case "str":
      if (typeof v !== "string") return `${p.name} must be text`;
      break;
  }
  if (p.choices && !p.choices.some((c) => same(c, v))) return `${p.name} must be one of ${p.choices.join(", ")}`;
  if (typeof v === "number") {
    if (p.minimum !== null && v < p.minimum) return `${p.name} must be at least ${p.minimum}`;
    if (p.maximum !== null && v > p.maximum) return `${p.name} must be at most ${p.maximum}`;
  }
  return null;
}

/** Defaults + given params, minus parameters whose `applies_when` is not met (no validation). */
export function resolveParams(spec: ModelSpec, params: Record<string, ParamValue>): Record<string, ParamValue> {
  const values: Record<string, ParamValue> = {};
  for (const p of spec.params) values[p.name] = p.name in params ? params[p.name] : p.default;
  const out: Record<string, ParamValue> = {};
  for (const p of spec.params) if (applies(p, values)) out[p.name] = values[p.name];
  return out;
}

export function cartesianCount(dimensions: Record<string, ParamValue[]>): number {
  const lists = Object.values(dimensions);
  if (lists.length === 0) return 1;
  return lists.reduce((n, l) => n * l.length, 1);
}

const ENUMERATION_CAP = 20000;

/**
 * Number of distinct grid variations after inapplicable parameters are dropped and duplicates collapse,
 * or null if the product is too large to enumerate in the browser.
 */
export function effectiveGridCount(spec: ModelSpec, plan: QuestionPlan): number | null {
  const dims = Object.entries(plan.grid.dimensions);
  const total = cartesianCount(plan.grid.dimensions);
  if (total === 0) return 0;
  if (total > ENUMERATION_CAP) return null;
  const seen = new Set<string>();
  const idx = new Array(dims.length).fill(0);
  for (let n = 0; n < total; n++) {
    const params: Record<string, ParamValue> = { ...plan.grid.fixed };
    dims.forEach(([name, values], i) => (params[name] = values[idx[i]]));
    const resolved = resolveParams(spec, params);
    seen.add(JSON.stringify(Object.keys(resolved).sort().map((k) => [k, resolved[k]])));
    for (let i = dims.length - 1; i >= 0; i--) {
      idx[i]++;
      if (idx[i] < dims[i][1].length) break;
      idx[i] = 0;
    }
  }
  return seen.size;
}

/** Problems that would make the server reject the plan (shown before submit). */
export function planProblems(spec: ModelSpec | undefined, plan: QuestionPlan, extraSpecs: Record<string, ModelSpec>): string[] {
  if (!spec) return [`Unknown grid model ${plan.grid.model_id}`];
  const problems: string[] = [];
  const byName = new Map(spec.params.map((p) => [p.name, p]));
  for (const [name, values] of Object.entries(plan.grid.dimensions)) {
    const p = byName.get(name);
    if (!p) problems.push(`Unknown parameter ${name}`);
    else if (values.length === 0) problems.push(`Choose at least one value for ${name}, or stop varying it`);
    else for (const v of values) {
      const m = checkParamValue(p, v);
      if (m) problems.push(m);
    }
  }
  for (const [name, v] of Object.entries(plan.grid.fixed)) {
    const p = byName.get(name);
    if (!p) problems.push(`Unknown parameter ${name}`);
    else {
      const m = checkParamValue(p, v);
      if (m) problems.push(m);
    }
  }
  plan.extras.forEach((e) => {
    const es = extraSpecs[e.model_id];
    if (!es) return;
    for (const [name, v] of Object.entries(e.params)) {
      const p = es.params.find((x) => x.name === name);
      const m = p ? checkParamValue(p, v) : `Unknown parameter ${name} for ${e.model_id}`;
      if (m) problems.push(`${e.model_id}: ${m}`);
    }
  });
  const count = effectiveGridCount(spec, plan) ?? cartesianCount(plan.grid.dimensions);
  if (count + plan.extras.length > plan.max_variations) {
    problems.push(`${count + plan.extras.length} variations exceed the plan limit of ${plan.max_variations}`);
  }
  if (!Number.isInteger(plan.max_variations) || plan.max_variations < 1 || plan.max_variations > 1000) {
    problems.push("Maximum variations must be a whole number from 1 to 1000");
  }
  return problems;
}
