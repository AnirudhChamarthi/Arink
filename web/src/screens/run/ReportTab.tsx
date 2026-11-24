import { useAsync } from "../../api/context";
import type { RunRecord } from "../../api/types";
import { ErrorPanel, Loading, RatingBadge } from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { Markdown } from "../../lib/markdown";

export function downloadText(filename: string, text: string, type = "text/markdown") {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportTab({ run }: { run: RunRecord }) {
  const report = useAsync((api) => api.getReport(run.run_id), [run.run_id, run.status]);
  if (report.status === "loading") return <Loading label="Loading report" />;
  if (report.status === "error") return <ErrorPanel error={report.error} onRetry={report.reload} />;
  const r = report.data;
  return (
    <div className="tab-body">
      <div className="report-head">
        <div>
          {r.signoff ? (
            <p>
              <span className={`badge outcome-${r.signoff.decision === "approve" ? "pass" : "fail"}`}>{r.signoff.decision === "approve" ? "Approved" : "Rejected"}</span> by{" "}
              <strong>{r.signoff.reviewer}</strong> · {formatDateTime(r.signoff.at)}
              {r.signoff.comment && <span className="muted"> — “{r.signoff.comment}”</span>}
            </p>
          ) : (
            <p className="muted">Draft report — not yet signed off.</p>
          )}
          <p className="small">
            Overall rating (judgment) <RatingBadge rating={r.assessment.overall} />
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => downloadText(`riskbot-${r.run.run_id}.md`, r.markdown)}>
          Download .md
        </button>
      </div>
      {r.headline.length > 0 && (
        <section className="headline" aria-label="Headline">
          <ul>
            {r.headline.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
          <p className="small muted">Every number in the headline is verified against the model traces.</p>
        </section>
      )}
      <article className="report-body">
        <Markdown source={r.markdown} />
      </article>
    </div>
  );
}
