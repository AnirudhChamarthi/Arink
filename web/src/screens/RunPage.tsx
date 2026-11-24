import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { isSettled, pollRun, toErrorBody } from "../api/client";
import { useApiConfig, useAsync } from "../api/context";
import type { ErrorBody, FactorEdit, RunRecord, RunStatus } from "../api/types";
import { CopyButton, ErrorPanel, Loading, StatusBadge, SyntheticBanner } from "../components/ui";
import { formatDateTime, shortHash } from "../lib/format";
import { datasetCurrency, useDraft } from "../lib/draft";
import { runHref } from "../lib/links";
import { questionTag } from "./Home";
import { AssessmentTab } from "./run/AssessmentTab";
import { AuditTab } from "./run/AuditTab";
import { OverviewTab } from "./run/OverviewTab";
import { ReportTab } from "./run/ReportTab";
import { ReviewTab } from "./run/ReviewTab";
import { SensitivityTab } from "./run/SensitivityTab";
import { VariationsTab } from "./run/VariationsTab";

const TABS = [
  ["overview", "Overview"],
  ["variations", "Variations"],
  ["sensitivity", "Sensitivity"],
  ["assessment", "Assessment"],
  ["review", "Review"],
  ["report", "Report"],
  ["audit", "Audit log"],
] as const;
type Tab = (typeof TABS)[number][0];

const STEPS: { key: RunStatus[]; label: string }[] = [
  { key: ["pending"], label: "Queued" },
  { key: ["running"], label: "Running variations" },
  { key: ["awaiting_review"], label: "Awaiting review" },
  { key: ["approved", "rejected"], label: "Signed off" },
];

function Progress({ run, elapsed, pollMs }: { run: RunRecord; elapsed: number; pollMs: number }) {
  const idx = run.status === "failed" ? -1 : STEPS.findIndex((s) => s.key.includes(run.status));
  const active = !isSettled(run.status);
  return (
    <div className="progress">
      <ol className="stepper" aria-label="Run progress">
        {STEPS.map((s, i) => (
          <li key={s.label} className={i < idx ? "done" : i === idx ? "current" : ""} aria-current={i === idx ? "step" : undefined}>
            <span className="step-dot" aria-hidden="true" />
            {i === 3 && (run.status === "approved" || run.status === "rejected") ? (run.status === "approved" ? "Approved" : "Rejected") : s.label}
          </li>
        ))}
      </ol>
      {active && (
        <div className="progress-live">
          <div className="bar indeterminate" role="progressbar" aria-label="Run in progress" aria-valuetext={`${run.status}, ${Math.round(elapsed)} seconds`}>
            <span />
          </div>
          <p className="small muted" aria-live="polite">
            {run.status === "pending" ? "Queued" : `Running ${run.n_variations} variations`} · {Math.round(elapsed)} s · checking every {(pollMs / 1000).toFixed(1)} s
          </p>
        </div>
      )}
      {run.status === "failed" && (
        <ErrorPanel error={{ code: "internal", message: run.error ?? "The run failed without an error message.", details: {} }} title="Run failed" />
      )}
    </div>
  );
}

function TabBar({ runId, tab }: { runId: string; tab: Tab }) {
  const navigate = useNavigate();
  const refs = useRef<(HTMLAnchorElement | null)[]>([]);
  function onKey(e: KeyboardEvent, i: number) {
    let j = -1;
    if (e.key === "ArrowRight") j = (i + 1) % TABS.length;
    if (e.key === "ArrowLeft") j = (i - 1 + TABS.length) % TABS.length;
    if (e.key === "Home") j = 0;
    if (e.key === "End") j = TABS.length - 1;
    if (j < 0) return;
    e.preventDefault();
    navigate(runHref(runId, TABS[j][0]), { replace: true });
    refs.current[j]?.focus();
  }
  return (
    <div className="tabs" role="tablist" aria-label="Run sections">
      {TABS.map(([key, label], i) => (
        <Link
          key={key}
          ref={(el) => {
            refs.current[i] = el;
          }}
          to={runHref(runId, key)}
          replace
          role="tab"
          id={`tab-${key}`}
          aria-selected={tab === key}
          aria-controls="run-tabpanel"
          tabIndex={tab === key ? 0 : -1}
          className={`tab${tab === key ? " active" : ""}`}
          onKeyDown={(e) => onKey(e, i)}
        >
          {label}
        </Link>
      ))}
    </div>
  );
}

export function RunPage() {
  const { runId = "", tab: tabParam } = useParams();
  const tab: Tab = (TABS.find(([k]) => k === tabParam)?.[0] ?? "overview") as Tab;
  const { api, pollMs } = useApiConfig();
  const { draft } = useDraft();
  const [run, setRun] = useState<RunRecord | null>(null);
  const [runError, setRunError] = useState<ErrorBody | null>(null);
  const [edits, setEdits] = useState<FactorEdit[]>([]);
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [pollNonce, setPollNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setRunError(null);
    pollRun(api, runId, { intervalMs: pollMs, signal: ctrl.signal, onUpdate: setRun }).catch((e) => {
      if (!(e instanceof DOMException && e.name === "AbortError")) setRunError(toErrorBody(e));
    });
    return () => ctrl.abort();
  }, [api, runId, pollMs, pollNonce]);

  const active = run !== null && !isSettled(run.status);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);

  const hasResult = run !== null && run.status !== "failed" && isSettled(run.status);
  const result = useAsync((a) => (hasResult ? a.getResult(runId) : new Promise<never>(() => undefined)), [runId, hasResult, run?.status]);
  const models = useAsync((a) => (run ? a.models(run.question) : new Promise<never>(() => undefined)), [run?.question]);
  const currency = datasetCurrency(draft?.dataset && draft.dataset.name === run?.dataset_name ? draft.dataset : undefined);

  if (runError) {
    return (
      <div className="page">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/">Questions</Link> <span aria-hidden="true">/</span> <span>Run {runId}</span>
        </nav>
        <ErrorPanel error={runError} onRetry={() => setPollNonce((n) => n + 1)} title={runError.code === "not_found" ? "Run not found" : undefined} />
      </div>
    );
  }
  if (!run) return <div className="page"><Loading label="Loading run" /></div>;

  const specs = models.status === "ready" ? models.data : [];

  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Questions</Link> <span aria-hidden="true">/</span> <span>Run</span>
      </nav>
      <header className="page-head run-head">
        <div>
          <p className="eyebrow">
            {questionTag(run.question)} · {run.dataset_name}
          </p>
          <h1 className="run-title">
            Run <span className="mono">{run.run_id}</span> <StatusBadge status={run.status} />
          </h1>
          <p className="small muted">
            Created {formatDateTime(run.created_at)} · updated {formatDateTime(run.updated_at)} · {run.n_variations} variations · contract{" "}
            {run.contract_version}
          </p>
        </div>
        <div className="hash-box">
          <span className="small muted">Input hash</span>
          <code title={run.input_hash}>{shortHash(run.input_hash, 16)}</code>
          <CopyButton text={run.input_hash} label="Copy hash" />
        </div>
      </header>
      {run.synthetic && <SyntheticBanner subject="run's dataset" />}
      <Progress run={run} elapsed={(now - started) / 1000} pollMs={pollMs} />

      {hasResult && (
        <>
          <TabBar runId={run.run_id} tab={tab} />
          <div className="tabpanel" role="tabpanel" id="run-tabpanel" aria-labelledby={`tab-${tab}`}>
            {result.status === "loading" && <Loading label="Loading results" />}
            {result.status === "error" && <ErrorPanel error={result.error} onRetry={result.reload} />}
            {result.status === "ready" && (
              <>
                {tab === "overview" && <OverviewTab result={result.data} specs={specs} currency={currency} />}
                {tab === "variations" && <VariationsTab result={result.data} specs={specs} currency={currency} />}
                {tab === "sensitivity" && <SensitivityTab result={result.data} specs={specs} currency={currency} />}
                {tab === "assessment" && (
                  <AssessmentTab assessment={result.data.assessment} canEdit={run.status === "awaiting_review"} edits={edits} onEditsChange={setEdits} />
                )}
                {tab === "review" && (
                  <ReviewTab
                    run={run}
                    edits={edits}
                    factorNames={Object.fromEntries(result.data.assessment.factors.map((f) => [f.factor_id, f.name]))}
                    onReviewed={(rec) => {
                      setRun(rec);
                      setEdits([]);
                    }}
                  />
                )}
                {tab === "report" && <ReportTab run={run} />}
                {tab === "audit" && <AuditTab run={run} />}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
