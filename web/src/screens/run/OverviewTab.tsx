import type { ModelSpec, RunResult } from "../../api/types";
import { Empty, MetricCell, MetricValue, RatingBadge } from "../../components/ui";
import { formatParam, humanize, unitLabel } from "../../lib/format";
import { findMetric, metricSpec } from "./helpers";

export function OverviewTab({ result, specs, currency }: { result: RunResult; specs: ModelSpec[]; currency?: string }) {
  const { comparison: c, variations, plan } = result;
  const grid = variations.filter((v) => v.spec.role === "grid");
  const ok = grid.filter((v) => v.output && !v.error).length;
  const failed = variations.filter((v) => v.error).length;
  const extras = variations.filter((v) => v.spec.role === "extra");
  const ranges = Object.entries(c.metric_ranges);
  const opts = { currency };

  return (
    <div className="tab-body">
      <div className="stat-row">
        <div className="stat">
          <span className="stat-label">Grid variations</span>
          <span className="stat-value">
            {ok}
            <span className="stat-of"> / {grid.length} succeeded</span>
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Errors</span>
          <span className={`stat-value${failed ? " text-bad" : ""}`}>{failed}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Extra runs</span>
          <span className="stat-value">{extras.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Overall rating · judgment</span>
          <span className="stat-value">
            <RatingBadge rating={result.assessment.overall} />
          </span>
        </div>
      </div>

      <section className="section" aria-labelledby="ranges-h">
        <h3 id="ranges-h" className="section-title">
          Metric ranges across the grid <span className="muted small">({plan.grid.model_id})</span>
        </h3>
        {ranges.length === 0 ? (
          <Empty title="No metric ranges">No grid variation produced metrics.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Unit</th>
                  <th scope="col" className="num">
                    Min
                  </th>
                  <th scope="col" className="num">
                    Median
                  </th>
                  <th scope="col" className="num">
                    Max
                  </th>
                  <th scope="col" className="num">
                    n
                  </th>
                  <th scope="col" className="num" title="Max / min of per-method medians">
                    Method spread
                  </th>
                </tr>
              </thead>
              <tbody>
                {ranges.map(([key, r]) => {
                  const ms = metricSpec(specs, key, plan.grid.model_id);
                  const lo = findMetric(variations, key, r.min);
                  const hi = findMetric(variations, key, r.max);
                  return (
                    <tr key={key}>
                      <th scope="row">
                        <span className="metric-name">{humanize(key)}</span>
                        {ms && <span className="metric-desc">{ms.description}</span>}
                      </th>
                      <td className="small muted">{unitLabel(r.unit, currency)}</td>
                      <td className="num">
                        <MetricValue value={r.min} unit={r.unit} traceId={lo?.trace_id} step={lo?.trace_step} opts={opts} />
                      </td>
                      <td className="num strong">
                        <MetricValue value={r.median} unit={r.unit} opts={opts} />
                      </td>
                      <td className="num">
                        <MetricValue value={r.max} unit={r.unit} traceId={hi?.trace_id} step={hi?.trace_step} opts={opts} />
                      </td>
                      <td className="num">{r.n}</td>
                      <td className="num">{c.method_spread[key] !== undefined ? `${c.method_spread[key].toFixed(2)}×` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="small muted">Min and max link to the working of the variation that produced them. Medians are computed across variations.</p>
          </div>
        )}
      </section>

      <div className="two-col">
        <section className="section" aria-labelledby="labels-h">
          <h3 id="labels-h" className="section-title">
            Outcome labels
          </h3>
          {Object.keys(c.label_counts).length === 0 ? (
            <Empty title="No label counts" />
          ) : (
            Object.entries(c.label_counts).map(([label, counts]) => {
              const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
              return (
                <div key={label} className="label-count">
                  <p className="label-name">{humanize(label)}</p>
                  <div className="segbar" role="img" aria-label={Object.entries(counts).map(([v, n]) => `${v}: ${n}`).join(", ")}>
                    {Object.entries(counts).map(([v, n]) => (
                      <span key={v} className={`seg seg-${v.replace(/[^a-z]/gi, "")}`} style={{ flexGrow: n / total }} title={`${v}: ${n}`} />
                    ))}
                  </div>
                  <ul className="inline-list">
                    {Object.entries(counts).map(([v, n]) => (
                      <li key={v}>
                        <span className={`dot seg-${v.replace(/[^a-z]/gi, "")}`} aria-hidden="true" /> {v} <strong className="num">{n}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })
          )}
        </section>

        <section className="section" aria-labelledby="flips-h">
          <h3 id="flips-h" className="section-title">
            Conclusion flips
          </h3>
          {c.flips.length === 0 ? (
            <Empty title="No flips">No single-parameter change altered the pass/fail conclusion.</Empty>
          ) : (
            <ul className="flip-list">
              {c.flips.map((f, i) => (
                <li key={i}>
                  <span className="mono">{f.dimension}</span> {f.from_value} → {f.to_value}:{" "}
                  <span className={`badge outcome-${f.outcome_from}`}>{f.outcome_from}</span> →{" "}
                  <span className={`badge outcome-${f.outcome_to}`}>{f.outcome_to}</span>
                  <p className="small muted">{f.description}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="section" aria-labelledby="be-h">
        <h3 id="be-h" className="section-title">
          Break-evens (reverse stress)
        </h3>
        {c.break_evens.length === 0 ? (
          <Empty title="No break-evens for this question" />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Break-even</th>
                <th scope="col" className="num">
                  Value
                </th>
                <th scope="col">Found</th>
                <th scope="col">Description</th>
              </tr>
            </thead>
            <tbody>
              {c.break_evens.map((b, i) => (
                <tr key={i}>
                  <th scope="row">{humanize(b.name.replace(/^breakeven_/, ""))}</th>
                  <td className="num">
                    {b.found ? <MetricValue value={b.value} unit={b.unit} traceId={b.trace_id} step={b.name} opts={opts} /> : <span className="muted">not breached</span>}
                  </td>
                  <td>{b.found ? "yes" : "no"}</td>
                  <td className="small">{b.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {extras.length > 0 && (
        <section className="section" aria-labelledby="extras-h2">
          <h3 id="extras-h2" className="section-title">
            Extra runs
          </h3>
          <div className="extra-grid">
            {extras.map((v) => (
              <div key={v.spec.variation_id} className="card card-tight">
                <p className="mono strong">{v.spec.model_id}</p>
                {Object.keys(v.spec.params).length > 0 && (
                  <p className="small muted">{Object.entries(v.spec.params).map(([k, x]) => `${k}=${formatParam(x)}`).join(", ")}</p>
                )}
                {v.error && <p className="text-bad small">{v.error}</p>}
                {v.output && (
                  <dl className="kv compact">
                    {Object.entries(v.output.metrics).map(([k, m]) => (
                      <div key={k} className="kv-row">
                        <dt>{humanize(k)}</dt>
                        <dd>
                          <MetricCell metric={m} opts={opts} />
                        </dd>
                      </div>
                    ))}
                    {Object.entries(v.output.labels).map(([k, l]) => (
                      <div key={k} className="kv-row">
                        <dt>{humanize(k)}</dt>
                        <dd>
                          <span className="badge">{l}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {result.verifier_findings.length > 0 && (
        <section className="section" aria-labelledby="ver-h">
          <h3 id="ver-h" className="section-title">
            Number verifier
          </h3>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Location</th>
                <th scope="col">Text</th>
                <th scope="col">Matched</th>
                <th scope="col">Message</th>
              </tr>
            </thead>
            <tbody>
              {result.verifier_findings.map((f, i) => (
                <tr key={i} className={f.matched ? "" : "row-bad"}>
                  <td className="mono small">{f.location}</td>
                  <td>{f.text}</td>
                  <td>{f.matched ? "yes" : "no"}</td>
                  <td className="small">{f.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
