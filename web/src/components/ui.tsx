/** Small shared presentational components. */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ErrorBody, Metric, Rating, RunStatus, Severity, Unit } from "../api/types";
import { formatValue, type FormatOptions } from "../lib/format";
import { traceHref } from "../lib/links";

export function SyntheticBanner({ subject = "dataset" }: { subject?: string }) {
  return (
    <div className="banner banner-synthetic" role="note">
      <strong>Synthetic data.</strong> This {subject} was generated for demonstration. Figures are illustrative and do not
      describe any real portfolio or institution.
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty">
      <p className="state-title">{title}</p>
      {children && <div className="state-body">{children}</div>}
    </div>
  );
}

const CODE_LABELS: Record<ErrorBody["code"], string> = {
  not_found: "Not found",
  validation_failed: "Validation failed",
  conflict: "Not available in the current state",
  limit_exceeded: "Limit exceeded",
  internal: "Error",
};

export function ErrorPanel({ error, onRetry, title }: { error: ErrorBody; onRetry?: () => void; title?: string }) {
  const hasDetails = Object.keys(error.details ?? {}).length > 0;
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">
        {title ?? CODE_LABELS[error.code] ?? "Error"} <span className="code-tag">{error.code}</span>
      </p>
      <p className="error-message">{error.message}</p>
      {hasDetails && (
        <details>
          <summary>Details</summary>
          <pre className="json">{JSON.stringify(error.details, null, 2)}</pre>
        </details>
      )}
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

const STATUS_LABELS: Record<RunStatus, string> = {
  pending: "Pending",
  running: "Running",
  awaiting_review: "Awaiting review",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return <span className={`badge status status-${status}`}>{STATUS_LABELS[status]}</span>;
}

export function statusLabel(status: RunStatus) {
  return STATUS_LABELS[status];
}

export function RatingBadge({ rating }: { rating: Rating }) {
  return <span className={`badge rating rating-${rating}`}>{rating}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge severity severity-${severity}`}>{severity}</span>;
}

/** A formatted metric value that links to the trace step that produced it. */
export function MetricValue({
  value,
  unit,
  traceId,
  step,
  opts,
}: {
  value: number | null;
  unit: Unit | null;
  traceId?: string | null;
  step?: string | null;
  opts?: FormatOptions;
}) {
  const text = formatValue(value, unit, opts);
  if (!traceId) return <span className="num">{text}</span>;
  return (
    <Link className="num metric-link" to={traceHref(traceId, step)} title={`Show working: ${traceId}${step ? ` › ${step}` : ""}`}>
      {text}
    </Link>
  );
}

export function MetricCell({ metric, opts }: { metric: Metric | undefined; opts?: FormatOptions }) {
  if (!metric) return <span className="muted">—</span>;
  return <MetricValue value={metric.value} unit={metric.unit} traceId={metric.trace_id} step={metric.trace_step} opts={opts} />;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 1800);
  }
  return (
    <button type="button" className="btn btn-small btn-secondary" onClick={copy} aria-live="polite">
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label}
    </button>
  );
}

export function KeyValue({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
