import katex from "katex";
import "katex/dist/katex.min.css";
import { useEffect, useMemo, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useAsync } from "../api/context";
import type { Json, TableCell, TraceStep } from "../api/types";
import { CopyButton, Empty, ErrorPanel, KeyValue, Loading } from "../components/ui";
import { formatParam, formatValue, humanize, unitLabel } from "../lib/format";

/**
 * Render LaTeX with KaTeX. KaTeX escapes all text it emits, `trust: false` disables \href, \url,
 * \includegraphics and HTML-producing commands, and `throwOnError: false` renders bad input as a red
 * error span instead of throwing. This is the only HTML injected into the page.
 */
export function Tex({ source, display = false }: { source: string; display?: boolean }) {
  const html = useMemo(
    () => katex.renderToString(source, { throwOnError: false, displayMode: display, trust: false, strict: "ignore", output: "htmlAndMathml" }),
    [source, display],
  );
  return <span className={display ? "tex tex-display" : "tex"} dangerouslySetInnerHTML={{ __html: html }} />;
}

/** Substitutions are "plain text or LaTeX": treat as LaTeX only if it contains TeX syntax. */
export function looksLikeTex(s: string): boolean {
  return /\\[a-zA-Z]+|[\^_]\{|\\[{}]/.test(s);
}

function Cell({ v }: { v: TableCell }) {
  if (v === null) return <span className="muted">—</span>;
  if (typeof v === "boolean") return <>{v ? "yes" : "no"}</>;
  if (typeof v === "number") return <span className="num">{v.toLocaleString("en-US", { maximumFractionDigits: 6 })}</span>;
  return <>{v}</>;
}

const MAX_ROWS = 200;

function StepTable({ rows }: { rows: Record<string, TableCell>[] }) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return (
    <div className="table-scroll step-table">
      <table className="data-table compact">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_ROWS).map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c} className={typeof r[c] === "number" ? "num" : undefined}>
                  <Cell v={r[c] ?? null} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="small muted">Showing {MAX_ROWS} of {rows.length} rows.</p>}
    </div>
  );
}

function Step({ step, n, targeted }: { step: TraceStep; n: number; targeted: boolean }) {
  return (
    <li id={step.id} className={`trace-step${targeted ? " targeted" : ""}`} tabIndex={-1} aria-labelledby={`${step.id}-title`}>
      <div className="step-num" aria-hidden="true">
        {n}
      </div>
      <div className="step-body">
        <h2 id={`${step.id}-title`} className="step-title">
          <span className="visually-hidden">Step {n}: </span>
          {step.title} <a href={`#${step.id}`} className="step-anchor mono small" aria-label={`Link to step ${step.id}`}>#{step.id}</a>
        </h2>
        <div className="formula" aria-label="Formula">
          <Tex source={step.formula} display />
        </div>
        {step.substitution && (
          <div className="substitution">
            <span className="small muted">Substitution</span>
            {looksLikeTex(step.substitution) ? <Tex source={step.substitution} display /> : <p className="mono">{step.substitution}</p>}
          </div>
        )}
        {step.value !== null && (
          <p className="step-value">
            <span className="small muted">Value</span> <strong className="num">{formatValue(step.value, step.unit)}</strong>
            {step.unit && <span className="muted small"> ({unitLabel(step.unit)}; raw {step.value})</span>}
          </p>
        )}
        {step.table && step.table.length > 0 && <StepTable rows={step.table} />}
        {step.note && <p className="step-note small">{step.note}</p>}
      </div>
    </li>
  );
}

function renderInput(v: Json): string {
  if (v !== null && typeof v === "object") return JSON.stringify(v);
  return formatParam(v);
}

export function TraceViewer() {
  const { traceId = "" } = useParams();
  const { hash } = useLocation();
  const target = decodeURIComponent(hash.replace(/^#/, ""));
  const trace = useAsync((api) => api.getTrace(traceId), [traceId]);

  useEffect(() => {
    if (trace.status !== "ready" || !target) return;
    const el = document.getElementById(target);
    if (el) {
      el.scrollIntoView?.({ block: "start", behavior: "smooth" });
      el.focus?.({ preventScroll: true });
    }
  }, [trace.status, target]);

  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Questions</Link> <span aria-hidden="true">/</span> <span>Trace</span>
      </nav>
      {trace.status === "loading" && <Loading label="Loading trace" />}
      {trace.status === "error" && <ErrorPanel error={trace.error} onRetry={trace.reload} title={trace.error.code === "not_found" ? "Trace not found" : undefined} />}
      {trace.status === "ready" && (
        <>
          <header className="page-head">
            <p className="eyebrow">
              Trace · <span className="mono">{trace.data.model_id}</span>
            </p>
            <h1>{trace.data.title}</h1>
            <div className="hash-box inline">
              <span className="small muted">Trace</span> <code>{trace.data.trace_id}</code>
              <span className="small muted">Input hash</span>
              <code className="hash-full" title="SHA-256 of (model_id, dataset, params, seed)">
                {trace.data.input_hash}
              </code>
              <CopyButton text={trace.data.input_hash} label="Copy input hash" />
            </div>
          </header>
          {trace.data.warnings.length > 0 && (
            <div className="banner banner-warning" role="alert">
              <strong>Warnings</strong>
              <ul>
                {trace.data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="trace-layout">
            <aside className="trace-side" aria-label="Trace summary">
              <section className="card card-tight">
                <h2 className="h-small">Inputs</h2>
                {Object.keys(trace.data.inputs).length === 0 ? (
                  <p className="muted small">None recorded.</p>
                ) : (
                  <KeyValue
                    items={Object.entries(trace.data.inputs).flatMap(([k, v]): [string, ReactNode][] =>
                      v !== null && typeof v === "object" && !Array.isArray(v)
                        ? Object.entries(v).map(([k2, v2]) => [`${k}.${k2}`, <span className="mono small">{renderInput(v2)}</span>])
                        : [[k, <span className="mono small">{renderInput(v)}</span>]],
                    )}
                  />
                )}
              </section>
              <section className="card card-tight">
                <h2 className="h-small">Assumptions</h2>
                {trace.data.assumptions.length === 0 ? (
                  <p className="muted small">None stated.</p>
                ) : (
                  <ul className="assumptions">
                    {trace.data.assumptions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                )}
              </section>
              <section className="card card-tight">
                <h2 className="h-small">Results</h2>
                <KeyValue
                  items={Object.entries(trace.data.result).map(([k, v]) => {
                    const step = trace.data.steps.find((s) => s.id === k);
                    return [humanize(k), <a href={`#${k}`} className="num">{formatValue(v, step?.unit ?? null)}</a>];
                  })}
                />
              </section>
            </aside>
            <section aria-label="Steps" className="trace-steps">
              {trace.data.steps.length === 0 ? (
                <Empty title="This trace has no steps" />
              ) : (
                <ol className="step-list">
                  {trace.data.steps.map((s, i) => (
                    <Step key={s.id} step={s} n={i + 1} targeted={s.id === target} />
                  ))}
                </ol>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

export default TraceViewer;
