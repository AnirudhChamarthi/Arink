import { useAsync } from "../../api/context";
import type { RunRecord } from "../../api/types";
import { Empty, ErrorPanel, Loading } from "../../components/ui";
import { formatDateTime, humanize } from "../../lib/format";

export function AuditTab({ run }: { run: RunRecord }) {
  const audit = useAsync((api) => api.getAudit(run.run_id), [run.run_id, run.status, run.updated_at]);
  if (audit.status === "loading") return <Loading label="Loading audit log" />;
  if (audit.status === "error") return <ErrorPanel error={audit.error} onRetry={audit.reload} />;
  if (audit.data.length === 0) return <Empty title="No audit events recorded" />;
  return (
    <div className="tab-body">
      <ol className="audit-list">
        {audit.data.map((e, i) => (
          <li key={i} className={`audit-item actor-${e.actor === "system" ? "system" : e.actor === "llm" ? "llm" : "person"}`}>
            <time dateTime={e.at} className="small muted">
              {formatDateTime(e.at)}
            </time>
            <div>
              <p>
                <strong>{humanize(e.event)}</strong> <span className="tag">{e.actor}</span>
              </p>
              {Object.keys(e.detail).length > 0 && (
                <dl className="kv compact">
                  {Object.entries(e.detail).map(([k, v]) => (
                    <div className="kv-row" key={k}>
                      <dt>{k}</dt>
                      <dd className="mono small">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
