import { useId, useMemo, useState } from "react";
import type { ModelSpec, ParamValue, RunResult, VariationResult } from "../../api/types";
import { Empty, MetricCell } from "../../components/ui";
import { formatParam, humanize } from "../../lib/format";

type SortKey = { kind: "id" | "param" | "label" | "metric" | "duration"; name: string };
type Dir = "asc" | "desc";

function cellValue(v: VariationResult, key: SortKey): string | number | null {
  switch (key.kind) {
    case "id":
      return v.spec.variation_id;
    case "duration":
      return v.duration_ms;
    case "param": {
      const p = v.spec.params[key.name] as ParamValue | undefined;
      return p === undefined || p === null ? null : typeof p === "number" ? p : formatParam(p);
    }
    case "label":
      return v.output?.labels[key.name] ?? null;
    case "metric":
      return v.output?.metrics[key.name]?.value ?? null;
  }
}

function compare(a: string | number | null, b: string | number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1; // missing values sort last
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

export function VariationsTab({ result, specs, currency }: { result: RunResult; specs: ModelSpec[]; currency?: string }) {
  const models = useMemo(() => [...new Set(result.variations.map((v) => v.spec.model_id))], [result.variations]);
  const [model, setModel] = useState(result.plan.grid.model_id);
  const [filter, setFilter] = useState("");
  const [show, setShow] = useState<"all" | "ok" | "errors">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: Dir } | null>(null);
  const ids = { model: useId(), filter: useId(), show: useId() };

  const rows = result.variations.filter((v) => v.spec.model_id === model);
  const spec = specs.find((s) => s.model_id === model);
  const paramNames =
    model === result.plan.grid.model_id
      ? Object.keys(result.plan.grid.dimensions)
      : [...new Set(rows.flatMap((v) => Object.keys(v.spec.params)))];
  const present = new Set(rows.flatMap((v) => Object.keys(v.output?.metrics ?? {})));
  const metricKeys = [...(spec?.metrics.map((m) => m.key).filter((k) => present.has(k)) ?? []), ...[...present].filter((k) => !spec?.metrics.some((m) => m.key === k))];
  const labelKeys = [...new Set(rows.flatMap((v) => Object.keys(v.output?.labels ?? {})))];

  const needle = filter.trim().toLowerCase();
  const filtered = rows.filter((v) => {
    if (show === "ok" && v.error) return false;
    if (show === "errors" && !v.error) return false;
    if (!needle) return true;
    const hay = [
      v.spec.variation_id,
      ...Object.entries(v.spec.params).map(([k, x]) => `${k}=${formatParam(x)} ${formatParam(x)}`),
      ...Object.values(v.output?.labels ?? {}),
      v.error ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });
  const sorted = sort ? [...filtered].sort((a, b) => compare(cellValue(a, sort.key), cellValue(b, sort.key)) * (sort.dir === "asc" ? 1 : -1)) : filtered;
  const columns: { key: SortKey; label: string; numeric: boolean }[] = [
    { key: { kind: "id", name: "id" }, label: "Variation", numeric: false },
    ...paramNames.map((n) => ({ key: { kind: "param" as const, name: n }, label: n, numeric: false })),
    ...labelKeys.map((n) => ({ key: { kind: "label" as const, name: n }, label: humanize(n), numeric: false })),
    ...metricKeys.map((n) => ({ key: { kind: "metric" as const, name: n }, label: humanize(n), numeric: true })),
    { key: { kind: "duration", name: "duration" }, label: "ms", numeric: true },
  ];
  const same = (a: SortKey, b: SortKey) => a.kind === b.kind && a.name === b.name;
  const toggle = (key: SortKey) =>
    setSort((s) => (s && same(s.key, key) ? (s.dir === "asc" ? { key, dir: "desc" } : null) : { key, dir: "asc" }));

  return (
    <div className="tab-body">
      <div className="toolbar" role="search">
        {models.length > 1 && (
          <label htmlFor={ids.model}>
            Model
            <select id={ids.model} value={model} onChange={(e) => { setModel(e.target.value); setSort(null); }}>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                  {m === result.plan.grid.model_id ? " (grid)" : " (extra)"}
                </option>
              ))}
            </select>
          </label>
        )}
        <label htmlFor={ids.filter}>
          Filter
          <input id={ids.filter} type="search" placeholder="e.g. historical, fail, 750" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label htmlFor={ids.show}>
          Show
          <select id={ids.show} value={show} onChange={(e) => setShow(e.target.value as typeof show)}>
            <option value="all">All rows</option>
            <option value="ok">Successful only</option>
            <option value="errors">Errors only</option>
          </select>
        </label>
        <p className="small muted toolbar-count" aria-live="polite">
          {sorted.length} of {rows.length} variation{rows.length === 1 ? "" : "s"}
        </p>
      </div>
      {sorted.length === 0 ? (
        <Empty title="No variations match">Clear the filter to see all rows.</Empty>
      ) : (
        <div className="table-scroll tall">
          <table className="data-table sticky-head variations-table">
            <caption className="visually-hidden">Variations of {model}: parameters, labels and metrics. Column headers sort the table.</caption>
            <thead>
              <tr>
                {columns.map((c) => {
                  const active = sort && same(sort.key, c.key);
                  return (
                    <th
                      key={`${c.key.kind}:${c.key.name}`}
                      scope="col"
                      className={c.numeric ? "num" : undefined}
                      aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"}
                    >
                      <button type="button" className="sort-btn" onClick={() => toggle(c.key)}>
                        {c.label}
                        <span className="sort-ind" aria-hidden="true">
                          {active ? (sort!.dir === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((v) => (
                <tr key={v.spec.variation_id} className={v.error ? "row-bad" : undefined}>
                  <td className="mono small">{v.spec.variation_id}</td>
                  {paramNames.map((n) => (
                    <td key={n}>{n in v.spec.params ? formatParam(v.spec.params[n]) : <span className="muted" title="Not applicable to this variation">n/a</span>}</td>
                  ))}
                  {v.error ? (
                    <td colSpan={labelKeys.length + metricKeys.length} className="error-cell">
                      <span className="badge severity-error">error</span> {v.error}
                    </td>
                  ) : (
                    <>
                      {labelKeys.map((n) => (
                        <td key={n}>
                          {v.output?.labels[n] ? <span className={`badge outcome-${v.output.labels[n]}`}>{v.output.labels[n]}</span> : "—"}
                        </td>
                      ))}
                      {metricKeys.map((n) => (
                        <td key={n} className="num">
                          <MetricCell metric={v.output?.metrics[n]} opts={{ currency }} />
                        </td>
                      ))}
                    </>
                  )}
                  <td className="num small muted">{v.duration_ms.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
