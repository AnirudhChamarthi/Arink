/**
 * Hand-written SVG charts. Single-series by design (one accent hue; text in ink tokens), each with an
 * accessible name, per-mark <title> tooltips and a companion table elsewhere on the page.
 */
import { useEffect, useRef, useState } from "react";
import type { SensitivityRow, Unit } from "../api/types";
import { formatValue, humanize } from "../lib/format";

/** Track an element's width so SVG coordinates equal CSS pixels (text stays legible at any width). */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, Math.max(width, 320)] as const;
}

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const span = d1 - d0 || Math.abs(d0) || 1;
  return (v: number) => range[0] + ((v - d0) / span) * (range[1] - range[0]);
}

/**
 * Tornado chart: for each grid dimension, a bar spanning the lowest to the highest median of the metric
 * across that dimension's values, sorted by effect. A dashed line marks the overall median.
 */
export function Tornado({ rows, unit, median, currency, title }: { rows: SensitivityRow[]; unit: Unit; median?: number; currency?: string; title: string }) {
  const [ref, TW] = useWidth(900);
  const sorted = [...rows].sort((a, b) => b.effect - a.effect);
  const all = sorted.flatMap((r) => Object.values(r.medians));
  if (median !== undefined) all.push(median);
  if (all.length === 0) return null;
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const pad = (hi - lo) * 0.04 || Math.abs(hi) * 0.05 || 1;
  const left = Math.min(170, TW * 0.22);
  const right = TW - 16;
  // Leave room either side of the bars for the dimension-value labels.
  const x = scale([lo - pad, hi + pad], [left + 100, right - 100]);
  const rowH = 34;
  const top = 8;
  const height = top + sorted.length * rowH + 30;
  const fmt = (v: number) => formatValue(v, unit, { currency });

  return (
    <figure className="chart" ref={ref}>
      <svg viewBox={`0 0 ${TW} ${height}`} width={TW} height={height} role="img" aria-label={title} className="chart-svg">
        <title>{title}</title>
        {sorted.map((r, i) => {
          const entries = Object.entries(r.medians).sort((a, b) => a[1] - b[1]);
          const [minK, minV] = entries[0];
          const [maxK, maxV] = entries[entries.length - 1];
          const y = top + i * rowH;
          const x0 = x(minV);
          const x1 = Math.max(x(maxV), x0 + 2);
          return (
            <g key={r.dimension} className="tornado-row">
              <text x={left - 10} y={y + rowH / 2} dy="0.35em" textAnchor="end" className="chart-label">
                {humanize(r.dimension)}
              </text>
              <rect x={x0} y={y + 7} width={x1 - x0} height={rowH - 14} rx={3} className="chart-bar">
                <title>
                  {`${humanize(r.dimension)}: ${minK} → ${fmt(minV)}; ${maxK} → ${fmt(maxV)}; effect ${fmt(r.effect)}`}
                </title>
              </rect>
              <text x={x0 - 4} y={y + rowH / 2} dy="0.35em" textAnchor="end" className="chart-end">
                {minK}
              </text>
              <text x={x1 + 4} y={y + rowH / 2} dy="0.35em" className="chart-end">
                {maxK}
              </text>
            </g>
          );
        })}
        {median !== undefined && (
          <g>
            <line x1={x(median)} x2={x(median)} y1={top} y2={top + sorted.length * rowH} className="chart-ref" />
            <text x={x(median)} y={top + sorted.length * rowH + 12} textAnchor="middle" className="chart-axis">
              median {fmt(median)}
            </text>
          </g>
        )}
        <line x1={x(lo - pad)} x2={x(hi + pad)} y1={height - 8} y2={height - 8} className="chart-baseline" />
        <line x1={x(lo)} x2={x(lo)} y1={height - 12} y2={height - 4} className="chart-baseline" />
        <line x1={x(hi)} x2={x(hi)} y1={height - 12} y2={height - 4} className="chart-baseline" />
        <text x={x(lo) - 4} y={height - 12} textAnchor="end" className="chart-axis">
          {fmt(lo)}
        </text>
        <text x={x(hi) + 4} y={height - 12} className="chart-axis">
          {fmt(hi)}
        </text>
      </svg>
    </figure>
  );
}

/** Range strip: every variation's value as a dot on one axis, with min, median and max marked. */
export function RangeStrip({ values, unit, median, currency, label }: { values: number[]; unit: Unit; median: number; currency?: string; label: string }) {
  const [ref, W] = useWidth(560);
  if (values.length === 0) return null;
  const lo = Math.min(...values, median);
  const hi = Math.max(...values, median);
  const left = 12;
  const right = W - 12;
  const x = scale([lo, hi], [left + 6, right - 6]);
  const fmt = (v: number) => formatValue(v, unit, { currency });
  return (
    <div ref={ref}>
    <svg viewBox={`0 0 ${W} 54`} width={W} height={54} role="img" aria-label={`${label}: ${values.length} variations from ${fmt(lo)} to ${fmt(hi)}, median ${fmt(median)}`} className="chart-svg strip">
      <line x1={left} x2={right} y1={20} y2={20} className="chart-baseline" />
      {values.map((v, i) => (
        <circle key={i} cx={x(v)} cy={20} r={4.5} className="chart-dot">
          <title>{fmt(v)}</title>
        </circle>
      ))}
      <line x1={x(median)} x2={x(median)} y1={8} y2={32} className="chart-median" />
      <text x={left} y={48} className="chart-axis">
        min {fmt(lo)}
      </text>
      <text x={Math.min(Math.max(x(median), W * 0.3), W * 0.7)} y={48} textAnchor="middle" className="chart-axis chart-axis-strong">
        median {fmt(median)}
      </text>
      <text x={right} y={48} textAnchor="end" className="chart-axis">
        max {fmt(hi)}
      </text>
    </svg>
    </div>
  );
}
