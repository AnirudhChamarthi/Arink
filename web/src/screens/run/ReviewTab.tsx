import { useId, useState } from "react";
import { toErrorBody } from "../../api/client";
import { useApi } from "../../api/context";
import type { ErrorBody, FactorEdit, ReviewDecision, RunRecord } from "../../api/types";
import { ErrorPanel, StatusBadge } from "../../components/ui";

export function ReviewTab({
  run,
  edits,
  onReviewed,
  factorNames,
}: {
  run: RunRecord;
  edits: FactorEdit[];
  onReviewed: (r: RunRecord) => void;
  factorNames: Record<string, string>;
}) {
  const api = useApi();
  const [reviewer, setReviewer] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<ReviewDecision | null>(null);
  const [error, setError] = useState<ErrorBody | null>(null);
  const id = useId();
  const open = run.status === "awaiting_review";
  const disabled = !open || busy !== null;
  const nameMissing = reviewer.trim() === "";

  async function decide(decision: ReviewDecision) {
    if (nameMissing) {
      setError({ code: "validation_failed", message: "Enter the reviewer's name before signing off.", details: {} });
      return;
    }
    setBusy(decision);
    setError(null);
    try {
      const rec = await api.submitReview(run.run_id, { decision, reviewer: reviewer.trim(), comment: comment.trim(), factor_edits: edits });
      onReviewed(rec);
    } catch (e) {
      setError(toErrorBody(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="tab-body narrow">
      <div className="review-status">
        <span>Current status</span> <StatusBadge status={run.status} />
      </div>
      {!open && (
        <p className="notice" role="status">
          {run.status === "approved" || run.status === "rejected"
            ? `This run has been ${run.status}. Sign-off is final; see the report and audit log.`
            : run.status === "failed"
              ? "This run failed and cannot be reviewed."
              : "Review opens when the run reaches “awaiting review”."}
        </p>
      )}
      <section className="section" aria-labelledby={`${id}-edits`}>
        <h3 id={`${id}-edits`} className="section-title">
          Factor edits to submit
        </h3>
        {edits.length === 0 ? (
          <p className="muted small">None. Use the Assessment tab to change a rating; each change needs a reason.</p>
        ) : (
          <ul className="edit-summary">
            {edits.map((e) => (
              <li key={e.factor_id}>
                <strong>{factorNames[e.factor_id] ?? e.factor_id}</strong>:{" "}
                {(["likelihood", "impact", "control"] as const)
                  .filter((k) => e[k] !== undefined && e[k] !== null)
                  .map((k) => `${k} → ${e[k]}`)
                  .concat(e.rationale ? ["rationale rewritten"] : [])
                  .join(", ")}{" "}
                <span className="muted">— {e.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <form
        className="review-form"
        onSubmit={(e) => {
          e.preventDefault();
        }}
        aria-label="Sign-off"
      >
        <label htmlFor={`${id}-who`}>
          Reviewer name <span className="req">(required)</span>
          <input id={`${id}-who`} type="text" autoComplete="name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} disabled={!open} aria-required="true" />
        </label>
        <label htmlFor={`${id}-comment`}>
          Comment
          <textarea id={`${id}-comment`} rows={4} value={comment} onChange={(e) => setComment(e.target.value)} disabled={!open} />
        </label>
        {error && <ErrorPanel error={error} title="Review not recorded" />}
        <div className="actions">
          <button type="button" className="btn btn-approve" disabled={disabled} onClick={() => decide("approve")}>
            {busy === "approve" ? "Approving…" : "Approve"}
          </button>
          <button type="button" className="btn btn-reject" disabled={disabled} onClick={() => decide("reject")}>
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
        </div>
        <p className="small muted">The decision, your name, comment and every factor edit are written to the audit log.</p>
      </form>
    </div>
  );
}
