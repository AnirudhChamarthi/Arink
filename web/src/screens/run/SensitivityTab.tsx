import { useId, useState } from "react";
import type { ModelSpec, RunResult } from "../../api/types";
import { RangeStrip, Tornado } from "../../components/charts";
import { Empty } from "../../components/ui";
import { formatValue, humanize } from "../../lib/format";
import { metricSpec } from "./helpers";

export function SensitivityTab({ result, specs, currency }: { result: RunResult; specs: ModelSpec[]; currency?: string }) {
  const c = result.comparison;
  const metrics = [...new Set(c.sensitivity.map((r) => r.metric))];
  const [metric, setMetric] = useState(metrics[0] ?? "");
  const selectId = useId();
  const rows = c.sensitivity.filter((r) => r.metric === metric);
  const range = c.metric_ranges[metric];
  const unit = range?.unit ?? metricSpec(specs, metric)?.unit ?? "fraction";
  const fmt = (v: number) => formatValue(v, unit, { currency });
  const grid = result.variations.filter((v) => v.spec.role === "grid" && v.output);

  return (
    <div className="tab-body">
      <section className="section" aria-labelledby="tornado-h">
        <h3 id="tornado-h" className="section-title">
          Which assumption moves the answer most?
        </h3>
        {metrics.length === 0 ? (
          <Empty title="No sensitivity results">The comparison has no sensitivity rows for this run (needs at least two values in a grid dimension).</Empty>
        ) : (
          <>
            <div className="toolbar">
              <label htmlFor={selectId}>
                Metric
                <select id={selectId} value={metric} onChange={(e) => setMetric(e.target.value)}>
                  {metrics.map((m) => (
                    <option key={m} value={m}>
                      {humanize(m)}
                    </option>
                  ))}
                </select>
              </label>
              <p className="small muted">{metricSpec(specs, metric, result.plan.grid.model_id)?.description}</p>
            </div>
            <Tornado
              rows={rows}
              unit={unit}
              median={range?.median}
              currency={currency}
              title={`Sensitivity of ${humanize(metric)}: span of medians across each grid dimension`}
            />
            <p className="small muted">
              Each bar spans the lowest to the highest median of {humanize(metric)} across the values of one grid dimension, holding the
              others pooled; longer bars mean the conclusion depends more on that choice.
            </p>
            <details className="table-toggle">
              <summary>Show as table</summary>
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Dimension</th>
                    <th scope="col">Medians by value</th>
                    <th scope="col" className="num">
                      Effect (max − min)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...rows]
                    .sort((a, b) => b.effect - a.effect)
                    .map((r) => (
                      <tr key={r.dimension}>
                        <th scope="row" className="mono">
                          {r.dimension}
                        </th>
                        <td className="small">
                          {Object.entries(r.medians)
                            .map(([k, v]) => `${k}: ${fmt(v)}`)
                            .join(" · ")}
                        </td>
                        <td className="num">{fmt(r.effect)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </section>

      <section className="section" aria-labelledby="strips-h">
        <h3 id="strips-h" className="section-title">
          Range of every metric across grid variations
        </h3>
        {Object.keys(c.metric_ranges).length === 0 ? (
          <Empty title="No metric ranges" />
        ) : (
          <div className="strip-list">
            {Object.entries(c.metric_ranges).map(([key, r]) => {
              const values = grid.map((v) => v.output!.metrics[key]?.value).filter((x): x is number => typeof x === "number");
              return (
                <div key={key} className="strip-row">
                  <p className="strip-label">
                    {humanize(key)} <span className="muted small">n={r.n}</span>
                  </p>
                  <RangeStrip values={values.length ? values : [r.min, r.median, r.max]} unit={r.unit} median={r.median} currency={currency} label={humanize(key)} />
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
