import { useId, useState, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toErrorBody } from "../api/client";
import { useApi, useAsync } from "../api/context";
import type { DataQualityFinding, Dataset, ErrorBody, QuestionInfo, Severity } from "../api/types";
import { SEVERITIES } from "../api/types";
import { Empty, ErrorPanel, Loading, SeverityBadge, StatusBadge, SyntheticBanner } from "../components/ui";
import { formatDateTime, formatParam, humanize } from "../lib/format";
import { datasetSummary, useDraft, type Draft } from "../lib/draft";
import { runHref } from "../lib/links";
import { cartesianCount } from "../lib/plan";

const QUESTION_TAGS: Record<string, string> = {
  q1_market: "Q1 · Market",
  q2_balance_sheet: "Q2 · Balance sheet",
  q3_transition: "Q3 · Climate transition",
};

export function questionTag(q: string) {
  return QUESTION_TAGS[q] ?? q;
}

export function PlanSummary({ info }: { info: QuestionInfo }) {
  const plan = info.default_plan;
  const dims = Object.entries(plan.grid.dimensions);
  const fixed = Object.entries(plan.grid.fixed);
  return (
    <div className="plan-summary">
      <p className="plan-line">
        <span className="mono">{plan.grid.model_id}</span> grid of up to <strong>{cartesianCount(plan.grid.dimensions)}</strong> variations
        {plan.extras.length > 0 && (
          <>
            {" "}
            + {plan.extras.length} extra run{plan.extras.length > 1 ? "s" : ""}
          </>
        )}
      </p>
      <ul className="dim-list" aria-label="Default grid dimensions">
        {dims.map(([name, values]) => (
          <li key={name}>
            <span className="dim-name">{humanize(name)}</span>
            <span className="dim-values">{values.map(formatParam).join(" · ")}</span>
          </li>
        ))}
      </ul>
      {fixed.length > 0 && (
        <p className="muted small">
          Fixed: {fixed.map(([k, v]) => `${k} = ${formatParam(v)}`).join(", ")}
        </p>
      )}
      {plan.extras.length > 0 && (
        <p className="muted small">
          Extras:{" "}
          {plan.extras
            .map((e) => `${e.model_id}${Object.keys(e.params).length ? ` (${Object.entries(e.params).map(([k, v]) => `${k}=${formatParam(v)}`).join(", ")})` : ""}`)
            .join("; ")}
        </p>
      )}
    </div>
  );
}

export function FindingsList({ findings }: { findings: DataQualityFinding[] }) {
  if (findings.length === 0) return <p className="ok-note">No data-quality findings.</p>;
  const order: Severity[] = [...SEVERITIES].reverse();
  return (
    <div className="findings">
      {order.map((sev) => {
        const group = findings.filter((f) => f.severity === sev);
        if (group.length === 0) return null;
        return (
          <section key={sev} className={`finding-group finding-${sev}`} aria-label={`${sev} findings`}>
            <h4>
              <SeverityBadge severity={sev} /> {group.length} {sev === "info" ? "note" : sev}
              {group.length > 1 ? "s" : ""}
            </h4>
            <ul>
              {group.map((f, i) => (
                <li key={i}>
                  <span className="mono small">{f.check}</span> {f.message}
                  {f.subject && <span className="muted"> · {f.subject}</span>}
                  <span className="muted small"> ({f.field})</span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function QuestionCard({ info, index }: { info: QuestionInfo; index: number }) {
  const api = useApi();
  const navigate = useNavigate();
  const { draft, setDraft } = useDraft();
  const fileId = useId();
  const [busy, setBusy] = useState<null | "sample" | "upload">(null);
  const [error, setError] = useState<ErrorBody | null>(null);
  const current = draft && draft.question === info.question ? draft : null;

  async function adopt(dataset: Dataset, source: Draft["source"], fileName?: string) {
    const findings = await api.validateDataset(dataset);
    setDraft({ question: info.question, dataset, source, fileName, findings });
  }

  async function loadSample() {
    setBusy("sample");
    setError(null);
    try {
      await adopt(await api.sample(info.question), "sample");
    } catch (e) {
      setError(toErrorBody(e));
    } finally {
      setBusy(null);
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy("upload");
    setError(null);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw { code: "validation_failed", message: `${file.name} is not valid JSON.`, details: {} } satisfies ErrorBody;
      }
      const kind = parsed && typeof parsed === "object" ? (parsed as { kind?: unknown }).kind : undefined;
      if (kind !== info.dataset_kind) {
        throw {
          code: "validation_failed",
          message: `This question needs a "${info.dataset_kind}" dataset; the file has kind ${JSON.stringify(kind ?? null)}.`,
          details: {},
        } satisfies ErrorBody;
      }
      // The server is the validator: send the JSON as-is and show its findings or its error.
      await adopt(parsed as Dataset, "upload", file.name);
    } catch (err) {
      setError(err && typeof err === "object" && "code" in err && "message" in err ? (err as ErrorBody) : toErrorBody(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="card question-card" aria-labelledby={`q-${info.question}`}>
      <div className="question-head">
        <span className="q-number" aria-hidden="true">
          {index + 1}
        </span>
        <div>
          <p className="eyebrow">
            {questionTag(info.question)} · {humanize(info.dataset_kind)} dataset
          </p>
          <h2 id={`q-${info.question}`} className="question-title">
            {info.title}
          </h2>
          <p className="muted">{info.description}</p>
        </div>
      </div>
      <PlanSummary info={info} />
      <div className="actions">
        <button type="button" className="btn btn-primary" onClick={loadSample} disabled={busy !== null}>
          {busy === "sample" ? "Loading sample…" : "Use sample dataset"}
        </button>
        <input id={fileId} type="file" accept="application/json,.json" className="visually-hidden" onChange={upload} disabled={busy !== null} />
        <label htmlFor={fileId} className={`btn btn-secondary file-btn${busy ? " disabled" : ""}`}>
          {busy === "upload" ? "Validating…" : "Upload JSON…"}
        </label>
      </div>
      {error && <ErrorPanel error={error} title="Dataset rejected" />}
      {current && (
        <div className="dataset-panel" aria-live="polite">
          <div className="dataset-head">
            <div>
              <p className="eyebrow">{current.source === "sample" ? "Sample dataset" : `Uploaded · ${current.fileName}`}</p>
              <p className="dataset-name">{current.dataset.name}</p>
              <p className="muted small">
                As of {current.dataset.as_of} · {datasetSummary(current.dataset)}
              </p>
            </div>
            <button type="button" className="btn btn-primary" onClick={() => navigate(`/new/${info.question}`)}>
              Configure run →
            </button>
          </div>
          {current.dataset.synthetic && <SyntheticBanner />}
          <h3 className="h-small">Validation findings</h3>
          <FindingsList findings={current.findings} />
        </div>
      )}
    </article>
  );
}

function RecentRuns() {
  const runs = useAsync((api) => api.listRuns(10), []);
  if (runs.status === "loading") return <Loading label="Loading recent runs" />;
  if (runs.status === "error") return <ErrorPanel error={runs.error} onRetry={runs.reload} />;
  if (runs.data.length === 0) return <Empty title="No runs yet">Start one from a question above.</Empty>;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Question</th>
            <th scope="col">Dataset</th>
            <th scope="col">Status</th>
            <th scope="col" className="num">
              Variations
            </th>
            <th scope="col">Created</th>
          </tr>
        </thead>
        <tbody>
          {runs.data.map((r) => (
            <tr key={r.run_id}>
              <td>
                <Link to={runHref(r.run_id)} className="mono">
                  {r.run_id}
                </Link>
              </td>
              <td>{questionTag(r.question)}</td>
              <td>
                {r.dataset_name}
                {r.synthetic && <span className="tag tag-synthetic">synthetic</span>}
              </td>
              <td>
                <StatusBadge status={r.status} />
              </td>
              <td className="num">{r.n_variations}</td>
              <td className="small">{formatDateTime(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Home() {
  const questions = useAsync((api) => api.questions(), []);
  return (
    <div className="page">
      <header className="page-head">
        <p className="eyebrow">Riskbot v2</p>
        <h1>Three risk questions, answered with traceable numbers</h1>
        <p className="lede">
          Pick a question, start from a sample or your own dataset, and run a grid of model variations. Every figure links to the
          working that produced it; qualitative ratings are labelled as judgment and signed off by a reviewer.
        </p>
      </header>
      {questions.status === "loading" && <Loading label="Loading questions" />}
      {questions.status === "error" && <ErrorPanel error={questions.error} onRetry={questions.reload} />}
      {questions.status === "ready" &&
        (questions.data.length === 0 ? (
          <Empty title="The API offers no questions" />
        ) : (
          <div className="question-list">
            {questions.data.map((q, i) => (
              <QuestionCard key={q.question} info={q} index={i} />
            ))}
          </div>
        ))}
      <section className="section" aria-labelledby="recent-runs">
        <h2 id="recent-runs" className="section-title">
          Recent runs
        </h2>
        <RecentRuns />
      </section>
    </div>
  );
}
