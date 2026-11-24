import { Fragment, useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ControlStrength, Evidence, FactorEdit, QualitativeAssessment, QualitativeFactor } from "../../api/types";
import { CONTROL_STRENGTHS } from "../../api/types";
import { Empty, RatingBadge } from "../../components/ui";
import { formatDateTime, formatParam } from "../../lib/format";
import { traceHref } from "../../lib/links";
import { rate } from "../../lib/rules";

const SOURCE_LABELS: Record<QualitativeFactor["source"], string> = {
  rule: "Rule",
  llm_draft: "LLM draft",
  analyst: "Analyst",
  unassessed: "Unassessed",
};

function EvidenceItem({ e }: { e: Evidence }) {
  let ref: ReactNode = <span className="mono small">{e.ref}</span>;
  if (e.kind === "trace") {
    const [traceId, step] = e.ref.split("/", 2);
    ref = (
      <Link to={traceHref(traceId, step)} className="mono small">
        {e.ref}
      </Link>
    );
  }
  return (
    <li>
      <span className="tag">{e.kind.replace("_", " ")}</span> {ref} <span className="small">{e.description}</span>
    </li>
  );
}

/** Edit form for one factor. Emits a FactorEdit containing only changed fields plus the mandatory reason. */
export function FactorEditForm({ factor, initial, onSave, onCancel }: { factor: QualitativeFactor; initial?: FactorEdit; onSave: (e: FactorEdit) => void; onCancel: () => void }) {
  const [likelihood, setLikelihood] = useState(initial?.likelihood ?? factor.likelihood);
  const [impact, setImpact] = useState(initial?.impact ?? factor.impact);
  const [control, setControl] = useState<ControlStrength>(initial?.control ?? factor.control);
  const [rationale, setRationale] = useState(initial?.rationale ?? factor.rationale);
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const id = useId();
  const [inh, res] = rate(likelihood, impact, control);

  function save() {
    const edit: FactorEdit = { factor_id: factor.factor_id, reason: reason.trim() };
    if (likelihood !== factor.likelihood) edit.likelihood = likelihood;
    if (impact !== factor.impact) edit.impact = impact;
    if (control !== factor.control) edit.control = control;
    if (rationale.trim() !== factor.rationale.trim()) edit.rationale = rationale.trim();
    if (Object.keys(edit).length === 2) return setProblem("Change at least one field.");
    if (!edit.reason) return setProblem("A reason is required for every change; it is recorded in the audit trail.");
    setProblem(null);
    onSave(edit);
  }

  const scale = [1, 2, 3, 4, 5];
  return (
    <form
      className="edit-form"
      aria-label={`Edit ${factor.name}`}
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <div className="form-grid four">
        <label htmlFor={`${id}-l`}>
          Likelihood (1–5)
          <select id={`${id}-l`} value={likelihood} onChange={(e) => setLikelihood(Number(e.target.value))}>
            {scale.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label htmlFor={`${id}-i`}>
          Impact (1–5)
          <select id={`${id}-i`} value={impact} onChange={(e) => setImpact(Number(e.target.value))}>
            {scale.map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <label htmlFor={`${id}-c`}>
          Control
          <select id={`${id}-c`} value={control} onChange={(e) => setControl(e.target.value as ControlStrength)}>
            {CONTROL_STRENGTHS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <div className="preview-rating" aria-live="polite">
          <span className="small muted">Preview</span>
          <span>
            Inherent <RatingBadge rating={inh} /> · Residual <RatingBadge rating={res} />
          </span>
        </div>
      </div>
      <label htmlFor={`${id}-r`}>
        Rationale
        <textarea id={`${id}-r`} rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      <label htmlFor={`${id}-why`}>
        Reason for change <span className="req">(required)</span>
        <input id={`${id}-why`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} aria-required="true" aria-invalid={problem ? true : undefined} />
      </label>
      {problem && (
        <p className="field-error" role="alert">
          {problem}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary">
          Add edit to review
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function AssessmentTab({
  assessment,
  canEdit,
  edits,
  onEditsChange,
}: {
  assessment: QualitativeAssessment;
  canEdit: boolean;
  edits: FactorEdit[];
  onEditsChange: (edits: FactorEdit[]) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const cols = 9;
  return (
    <div className="tab-body">
      <div className="judgment-banner" role="note">
        <span className="judgment-label">Judgment</span>
        <div>
          <p>
            Qualitative ratings, not model outputs. Overall residual rating <RatingBadge rating={assessment.overall} />
          </p>
          <p className="small">{assessment.method_note}</p>
        </div>
      </div>
      {!canEdit && <p className="small muted">Edits are possible only while the run is awaiting review.</p>}
      {canEdit && edits.length > 0 && (
        <p className="small" role="status">
          {edits.length} pending edit{edits.length > 1 ? "s" : ""} will be submitted with the review.
        </p>
      )}
      {assessment.factors.length === 0 ? (
        <Empty title="No factors in this assessment" />
      ) : (
        <div className="table-scroll">
          <table className="data-table factor-table">
            <thead>
              <tr>
                <th scope="col">Factor</th>
                <th scope="col" className="num" title="Likelihood 1–5">
                  L
                </th>
                <th scope="col" className="num" title="Impact 1–5">
                  I
                </th>
                <th scope="col">Control</th>
                <th scope="col">Inherent</th>
                <th scope="col">Residual</th>
                <th scope="col">Rationale &amp; evidence</th>
                <th scope="col">Source</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {assessment.factors.map((f) => {
                const pending = edits.find((e) => e.factor_id === f.factor_id);
                return (
                  <Fragment key={f.factor_id}>
                    <tr className={pending ? "row-pending" : undefined}>
                      <th scope="row">
                        <span className="metric-name">{f.name}</span>
                        <span className="metric-desc">{f.description}</span>
                      </th>
                      <td className="num">{f.likelihood}</td>
                      <td className="num">{f.impact}</td>
                      <td>{f.control}</td>
                      <td>
                        <RatingBadge rating={f.inherent} />
                      </td>
                      <td>
                        <RatingBadge rating={f.residual} />
                      </td>
                      <td className="rationale">
                        <p>{f.rationale}</p>
                        {f.evidence.length > 0 && <ul className="evidence">{f.evidence.map((e, i) => <EvidenceItem key={i} e={e} />)}</ul>}
                        {pending && (
                          <p className="pending-note small">
                            Pending:{" "}
                            {(["likelihood", "impact", "control", "rationale"] as const)
                              .filter((k) => pending[k] !== undefined && pending[k] !== null)
                              .map((k) => (k === "rationale" ? "rationale" : `${k} → ${pending[k]}`))
                              .join(", ")}{" "}
                            — “{pending.reason}”
                          </p>
                        )}
                      </td>
                      <td>
                        <span className={`badge source source-${f.source}`}>{SOURCE_LABELS[f.source]}</span>
                      </td>
                      <td>
                        {canEdit && (
                          <div className="row-actions">
                            <button type="button" className="btn btn-small btn-secondary" onClick={() => setEditing(editing === f.factor_id ? null : f.factor_id)} aria-expanded={editing === f.factor_id} aria-label={`Edit ${f.name}`}>
                              Edit
                            </button>
                            {pending && (
                              <button type="button" className="btn btn-small btn-link" onClick={() => onEditsChange(edits.filter((e) => e !== pending))} aria-label={`Discard edit of ${f.name}`}>
                                Discard
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                    {editing === f.factor_id && canEdit && (
                      <tr className="edit-row">
                        <td colSpan={cols}>
                          <FactorEditForm
                            factor={f}
                            initial={pending}
                            onCancel={() => setEditing(null)}
                            onSave={(e) => {
                              onEditsChange([...edits.filter((x) => x.factor_id !== f.factor_id), e]);
                              setEditing(null);
                            }}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <section className="section" aria-labelledby="ovr-h">
        <h3 id="ovr-h" className="section-title">
          Override history
        </h3>
        {assessment.overrides.length === 0 ? (
          <Empty title="No overrides recorded" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Factor</th>
                <th scope="col">Field</th>
                <th scope="col">Old → new</th>
                <th scope="col">Reason</th>
                <th scope="col">By</th>
                <th scope="col">At</th>
              </tr>
            </thead>
            <tbody>
              {assessment.overrides.map((o, i) => (
                <tr key={i}>
                  <td className="mono small">{o.factor_id}</td>
                  <td>{o.field}</td>
                  <td>
                    {formatParam(o.old)} → {formatParam(o.new)}
                  </td>
                  <td>{o.reason}</td>
                  <td>{o.by}</td>
                  <td className="small">{formatDateTime(o.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
