/**
 * Contract conformance: hand-written types/decoders vs the generated JSON Schemas and fixtures.
 */
import { describe, expect, it } from "vitest";
import * as D from "./decoders";
import * as T from "./types";
import { validateSchema } from "../test/utils";

const schemas = import.meta.glob<Record<string, unknown>>("../mocks/schema/*.json", { eager: true, import: "default" });
const fixtures = import.meta.glob<unknown>("../mocks/fixtures/*.json", { eager: true, import: "default" });
const base = (p: string) => p.split("/").pop()!.replace(".json", "");
const schema = (name: string) => schemas[`../mocks/schema/${name}.json`];

/** fixture file -> [schema name, decoder] */
function routeFixture(name: string): [string, D.Decoder<unknown>, boolean] | null {
  if (name === "error_not_found") return ["ErrorBody", D.ErrorBody, false];
  if (name === "models") return ["ModelSpec", D.ModelSpec, true];
  if (name === "questions") return ["QuestionInfo", D.QuestionInfo, true];
  if (name.startsWith("report_")) return ["Report", D.Report, false];
  if (name.startsWith("run_record_")) return ["RunRecord", D.RunRecord, false];
  if (name.startsWith("run_result_")) return ["RunResult", D.RunResult, false];
  if (name.startsWith("sample_")) return ["Dataset", D.Dataset, false];
  if (name.startsWith("trace_")) return ["Trace", D.Trace, false];
  return null;
}

describe("fixtures conform to the contract", () => {
  const names = Object.keys(fixtures).map(base).sort();

  it("has the expected fixtures", () => {
    expect(names.length).toBeGreaterThanOrEqual(19);
    expect(Object.keys(schemas).length).toBeGreaterThanOrEqual(12);
  });

  for (const name of names) {
    const route = routeFixture(name);
    if (!route) continue;
    it(`${name} validates against ${route[0]}.json and its decoder`, () => {
      const [schemaName, decoder, isList] = route;
      const value = fixtures[`../mocks/fixtures/${name}.json`];
      const items = isList ? (value as unknown[]) : [value];
      expect(items.length).toBeGreaterThan(0);
      for (const item of items) {
        expect(validateSchema(schema(schemaName), item)).toEqual([]);
        const decoded = decoder(item);
        // Every field the server sent survives decoding unchanged.
        expect(decoded).toEqual(item);
      }
    });
  }

  it("contract_version fixture carries a version string", () => {
    expect(typeof (fixtures["../mocks/fixtures/contract_version.json"] as { contract_version: unknown }).contract_version).toBe("string");
  });
});

describe("decoders match the JSON Schemas field for field", () => {
  // Collect every object definition from every schema file (top-level and $defs).
  const defs = new Map<string, Record<string, unknown>>();
  for (const s of Object.values(schemas)) {
    if (s.properties && typeof s.title === "string") defs.set(s.title, s);
    for (const [k, d] of Object.entries((s.$defs ?? {}) as Record<string, Record<string, unknown>>)) if (d.properties) defs.set(k, d);
  }

  it("covers every object type in the schemas", () => {
    const missing = [...defs.keys()].filter((k) => !(k in D.OBJECT_DECODERS));
    expect(missing).toEqual([]);
  });

  for (const [name, def] of defs) {
    it(`${name}: same fields, same required set`, () => {
      const decoder = D.OBJECT_DECODERS[name];
      expect(decoder?.fields, `no decoder for ${name}`).toBeDefined();
      const props = Object.keys(def.properties as object).sort();
      expect([...decoder.fields!].sort()).toEqual(props);
    });
  }

  it("a field is required in the decoder exactly when the schema requires it", () => {
    const mismatches: string[] = [];
    for (const [name, def] of defs) {
      const shape = D.OBJECT_DECODERS[name].shape!;
      const schemaReq = new Set((def.required ?? []) as string[]);
      for (const [field, d] of Object.entries(shape)) {
        const decoderReq = !d.fallback && !d.optional;
        if (decoderReq !== schemaReq.has(field)) mismatches.push(`${name}.${field}`);
      }
    }
    expect(mismatches).toEqual([]);
  });

  it("enumerations match", () => {
    const enumOf = (n: string) => {
      for (const s of Object.values(schemas)) {
        const d = ((s.$defs ?? {}) as Record<string, { enum?: unknown[] }>)[n];
        if (d?.enum) return [...d.enum].sort();
      }
      return undefined;
    };
    expect(enumOf("Unit")).toEqual([...T.UNITS].sort());
    expect(enumOf("RunStatus")).toEqual([...T.RUN_STATUSES].sort());
    expect(enumOf("QuestionId")).toEqual([...T.QUESTION_IDS].sort());
    expect(enumOf("Rating")).toEqual([...T.RATINGS].sort());
    expect(enumOf("ControlStrength")).toEqual([...T.CONTROL_STRENGTHS].sort());
    expect(enumOf("FactorSource")).toEqual([...T.FACTOR_SOURCES].sort());
    expect(enumOf("Severity")).toEqual([...T.SEVERITIES].sort());
    expect(enumOf("DatasetKind")).toEqual([...T.DATASET_KINDS].sort());
    expect(enumOf("ReviewDecision")).toEqual([...T.REVIEW_DECISIONS].sort());
  });
});

describe("runtime guards", () => {
  it("reject unknown fields and wrong types with a path", () => {
    expect(() => D.RunRecord({ ...(fixtures["../mocks/fixtures/run_record_q1_market.json"] as object), extra: 1 })).toThrow(/unknown field\(s\) extra/);
    expect(() => D.RunRecord({ ...(fixtures["../mocks/fixtures/run_record_q1_market.json"] as object), status: "done" })).toThrow(/RunRecord\.status/);
    expect(() => D.Dataset({ kind: "bogus" })).toThrow(/kind/);
  });

  it("fill server defaults when absent", () => {
    const f = D.DataQualityFinding({ check: "c", severity: "info", field: "f", message: "m" });
    expect(f).toEqual({ check: "c", severity: "info", field: "f", subject: null, count: 0, message: "m" });
  });

  it("recognise ErrorBody", () => {
    expect(D.isErrorBody(fixtures["../mocks/fixtures/error_not_found.json"])).toBe(true);
    expect(D.isErrorBody({ detail: "x" })).toBe(false);
  });
});
