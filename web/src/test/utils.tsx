import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { RiskbotApi } from "../api/client";
import { ApiProvider } from "../api/context";
import { DraftProvider } from "../lib/draft";

/** Render `ui` at `route` (matching `path`) with an API and the app's providers. */
export function renderWith(ui: ReactElement, { api, route = "/", path = "/", pollMs = 5 }: { api: RiskbotApi; route?: string; path?: string; pollMs?: number }) {
  return render(
    <ApiProvider api={api} pollMs={pollMs}>
      <DraftProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="*" element={<p>other route</p>} />
          </Routes>
        </MemoryRouter>
      </DraftProvider>
    </ApiProvider>,
  );
}

/** Minimal JSON Schema (2020-12 subset used by pydantic) validator for the contract tests. */
type Schema = Record<string, unknown>;
export function validateSchema(root: Schema, value: unknown, schema: Schema = root, path = "$"): string[] {
  const errs: string[] = [];
  const defs = (root.$defs ?? {}) as Record<string, Schema>;
  if (typeof schema.$ref === "string") {
    const name = schema.$ref.replace("#/$defs/", "");
    return validateSchema(root, value, defs[name], path);
  }
  if (Array.isArray(schema.anyOf) || Array.isArray(schema.oneOf)) {
    const options = (schema.anyOf ?? schema.oneOf) as Schema[];
    const results = options.map((o) => validateSchema(root, value, o, path));
    const ok = results.filter((r) => r.length === 0).length;
    if (schema.oneOf ? ok !== 1 : ok === 0) errs.push(`${path}: matches ${ok} of ${options.length} alternatives (${results.flat().slice(0, 3).join("; ")})`);
    return errs;
  }
  if ("const" in schema && value !== schema.const) errs.push(`${path}: expected const ${JSON.stringify(schema.const)}`);
  if (Array.isArray(schema.enum) && !schema.enum.includes(value)) errs.push(`${path}: ${JSON.stringify(value)} not in enum`);
  const t = schema.type as string | undefined;
  const typeOk: Record<string, (v: unknown) => boolean> = {
    string: (v) => typeof v === "string",
    number: (v) => typeof v === "number",
    integer: (v) => typeof v === "number" && Number.isInteger(v),
    boolean: (v) => typeof v === "boolean",
    null: (v) => v === null,
    array: (v) => Array.isArray(v),
    object: (v) => typeof v === "object" && v !== null && !Array.isArray(v),
  };
  if (t && !typeOk[t](value)) return [`${path}: expected ${t}, got ${JSON.stringify(value)?.slice(0, 40)}`];
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) errs.push(`${path}: below minimum`);
    if (typeof schema.maximum === "number" && value > schema.maximum) errs.push(`${path}: above maximum`);
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) errs.push(`${path}: not above exclusiveMinimum`);
    if (typeof schema.exclusiveMaximum === "number" && value >= schema.exclusiveMaximum) errs.push(`${path}: not below exclusiveMaximum`);
  }
  if (typeof value === "string" && typeof schema.minLength === "number" && value.length < schema.minLength) errs.push(`${path}: too short`);
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) errs.push(`${path}: too few items`);
    if (schema.items) value.forEach((v, i) => errs.push(...validateSchema(root, v, schema.items as Schema, `${path}[${i}]`)));
  }
  if (t === "object" && typeof value === "object" && value) {
    const props = (schema.properties ?? {}) as Record<string, Schema>;
    for (const r of (schema.required ?? []) as string[]) if (!(r in value)) errs.push(`${path}: missing ${r}`);
    for (const [k, v] of Object.entries(value)) {
      if (k in props) errs.push(...validateSchema(root, v, props[k], `${path}.${k}`));
      else if (schema.additionalProperties === false) errs.push(`${path}: unexpected ${k}`);
      else if (typeof schema.additionalProperties === "object") errs.push(...validateSchema(root, v, schema.additionalProperties as Schema, `${path}.${k}`));
    }
  }
  return errs;
}
