import { useEffect, useId, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toErrorBody } from "../api/client";
import { useApi, useAsync } from "../api/context";
import type { Dataset, ErrorBody, ModelSpec, ParamSpec, ParamValue, QuestionId, QuestionInfo, QuestionPlan } from "../api/types";
import { QUESTION_IDS } from "../api/types";
import { Empty, ErrorPanel, Loading, SyntheticBanner } from "../components/ui";
import { formatParam } from "../lib/format";
import { datasetSummary, useDraft } from "../lib/draft";
import { runHref } from "../lib/links";
import { cartesianCount, checkParamValue, effectiveGridCount, planProblems } from "../lib/plan";
import { questionTag } from "./Home";

type Mode = "default" | "fixed" | "vary";

function NumberInput({ value, onChange, p, label }: { value: ParamValue; onChange: (v: number) => void; p: ParamSpec; label: string }) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => {
    if (Number(text) !== value) setText(value === null || Number.isNaN(value as number) ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  const problem = checkParamValue(p, value);
  const id = useId();
  return (
    <span className="num-input">
      <input
        id={id}
        type="number"
        inputMode="decimal"
        aria-label={label}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? `${id}-err` : undefined}
        min={p.minimum ?? undefined}
        max={p.maximum ?? undefined}
        step={p.type === "int" ? 1 : "any"}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(e.target.value.trim() === "" ? Number.NaN : Number(e.target.value));
        }}
      />
      {problem && (
        <span id={`${id}-err`} className="field-error">
          {problem}
        </span>
      )}
    </span>
  );
}

function FixedInput({ p, value, onChange }: { p: ParamSpec; value: ParamValue; onChange: (v: ParamValue) => void }) {
  const label = `${p.name} value`;
  if (p.type === "bool")
    return (
      <label className="check">
        <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} /> {value ? "true" : "false"}
      </label>
    );
  if (p.choices)
    return (
      <select aria-label={label} value={JSON.stringify(value)} onChange={(e) => onChange(JSON.parse(e.target.value))}>
        {p.choices.map((c) => (
          <option key={JSON.stringify(c)} value={JSON.stringify(c)}>
            {formatParam(c)}
          </option>
        ))}
      </select>
    );
  if (p.type === "str") return <input type="text" aria-label={label} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
  return <NumberInput p={p} value={value} onChange={onChange} label={label} />;
}

function VaryInput({ p, values, onChange }: { p: ParamSpec; values: ParamValue[]; onChange: (v: ParamValue[]) => void }) {
  const choices: ParamValue[] | null = p.type === "bool" ? [true, false] : p.choices;
  if (choices)
    return (
      <fieldset className="choice-set">
        <legend className="visually-hidden">Values of {p.name} to vary</legend>
        {choices.map((c) => {
          const on = values.some((v) => v === c);
          return (
            <label key={JSON.stringify(c)} className={`chip-check${on ? " on" : ""}`}>
              <input
                type="checkbox"
                checked={on}
                onChange={(e) => onChange(e.target.checked ? choices.filter((x) => x === c || values.includes(x)) : values.filter((v) => v !== c))}
              />
              {formatParam(c)}
            </label>
          );
        })}
      </fieldset>
    );
  return (
    <div className="value-list">
      {values.map((v, i) => (
        <span key={i} className="value-item">
          <NumberInput p={p} value={v} label={`${p.name} value ${i + 1}`} onChange={(n) => onChange(values.map((x, j) => (j === i ? n : x)))} />
          <button type="button" className="btn btn-icon" aria-label={`Remove ${p.name} value ${i + 1}`} onClick={() => onChange(values.filter((_, j) => j !== i))}>
            ×
          </button>
        </span>
      ))}
      <button type="button" className="btn btn-small btn-secondary" onClick={() => onChange([...values, values.length ? values[values.length - 1] : p.default])}>
        Add value
      </button>
    </div>
  );
}

function ParamRow({
  p,
  mode,
  fixedValue,
  values,
  allowVary,
  onMode,
  onFixed,
  onValues,
}: {
  p: ParamSpec;
  mode: Mode;
  fixedValue: ParamValue;
  values: ParamValue[];
  allowVary: boolean;
  onMode: (m: Mode) => void;
  onFixed: (v: ParamValue) => void;
  onValues: (v: ParamValue[]) => void;
}) {
  const id = useId();
  const range =
    p.minimum !== null || p.maximum !== null ? `range ${p.minimum ?? "−∞"} to ${p.maximum ?? "∞"}` : p.choices ? `${p.choices.length} choices` : p.type;
  return (
    <div className={`param-row mode-${mode}`}>
      <div className="param-meta">
        <label htmlFor={id} className="param-name mono">
          {p.name}
        </label>
        <p className="param-desc">{p.description}</p>
        <p className="param-facts small muted">
          {p.type} · {range} · default {formatParam(p.default)}
          {p.applies_when && (
            <>
              {" "}
              · applies only when{" "}
              {Object.entries(p.applies_when)
                .map(([k, vs]) => `${k} ∈ {${vs.map(formatParam).join(", ")}}`)
                .join(" and ")}
            </>
          )}
        </p>
      </div>
      <div className="param-control">
        <select id={id} className="mode-select" value={mode} onChange={(e) => onMode(e.target.value as Mode)} aria-label={`How to set ${p.name}`}>
          <option value="default">Default</option>
          <option value="fixed">Fixed</option>
          {allowVary && <option value="vary">Vary</option>}
        </select>
        <div className="param-input">
          {mode === "default" && <span className="muted">{formatParam(p.default)}</span>}
          {mode === "fixed" && <FixedInput p={p} value={fixedValue} onChange={onFixed} />}
          {mode === "vary" && <VaryInput p={p} values={values} onChange={onValues} />}
        </div>
      </div>
    </div>
  );
}

function PlanEditor({ info, models, dataset }: { info: QuestionInfo; models: ModelSpec[]; dataset: Dataset }) {
  const api = useApi();
  const navigate = useNavigate();
  const [plan, setPlan] = useState<QuestionPlan>(() => structuredClone(info.default_plan));
  const [included, setIncluded] = useState<boolean[]>(() => info.default_plan.extras.map(() => true));
  const [seed, setSeed] = useState(20261123);
  const [useLlm, setUseLlm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ErrorBody | null>(null);
  const specs = useMemo(() => Object.fromEntries(models.map((m) => [m.model_id, m])), [models]);
  const gridSpec = specs[plan.grid.model_id];

  const effectivePlan: QuestionPlan = useMemo(() => ({ ...plan, extras: plan.extras.filter((_, i) => included[i]) }), [plan, included]);
  const total = cartesianCount(plan.grid.dimensions);
  const effective = gridSpec ? effectiveGridCount(gridSpec, effectivePlan) : null;
  const problems = planProblems(gridSpec, effectivePlan, specs);
  if (!Number.isInteger(seed) || seed < 0) problems.push("Seed must be a non-negative whole number");
  const hasAppliesWhen = gridSpec?.params.some((p) => p.applies_when) ?? false;

  if (!gridSpec) return <ErrorPanel error={{ code: "not_found", message: `The catalogue has no model ${plan.grid.model_id}.`, details: {} }} />;

  function modeOf(name: string): Mode {
    return name in plan.grid.dimensions ? "vary" : name in plan.grid.fixed ? "fixed" : "default";
  }

  function setMode(p: ParamSpec, m: Mode) {
    setPlan((prev) => {
      const dims = { ...prev.grid.dimensions };
      const fixed = { ...prev.grid.fixed };
      const current = p.name in fixed ? fixed[p.name] : p.name in dims ? dims[p.name][0] : p.default;
      delete dims[p.name];
      delete fixed[p.name];
      if (m === "vary") dims[p.name] = [current ?? p.default];
      if (m === "fixed") fixed[p.name] = current ?? p.default;
      return { ...prev, grid: { ...prev.grid, dimensions: dims, fixed } };
    });
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const run = await api.startRun({ question: info.question, dataset, plan: effectivePlan, seed, use_llm: useLlm });
      navigate(runHref(run.run_id));
    } catch (e) {
      setError(toErrorBody(e));
      setSubmitting(false);
    }
  }

  const gridTotal = effective ?? total;
  const nExtras = effectivePlan.extras.length;

  return (
    <form
      className="plan-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (problems.length === 0) void submit();
      }}
    >
      <section className="card" aria-labelledby="grid-h">
        <h2 id="grid-h" className="card-title">
          Grid · <span className="mono">{gridSpec.model_id}</span>
        </h2>
        <p className="muted">{gridSpec.title}. Choose which parameters to vary; the grid is their cartesian product.</p>
        <div className="param-list">
          {gridSpec.params.map((p) => (
            <ParamRow
              key={p.name}
              p={p}
              mode={modeOf(p.name)}
              allowVary
              fixedValue={plan.grid.fixed[p.name] ?? p.default}
              values={plan.grid.dimensions[p.name] ?? []}
              onMode={(m) => setMode(p, m)}
              onFixed={(v) => setPlan((prev) => ({ ...prev, grid: { ...prev.grid, fixed: { ...prev.grid.fixed, [p.name]: v } } }))}
              onValues={(vs) => setPlan((prev) => ({ ...prev, grid: { ...prev.grid, dimensions: { ...prev.grid.dimensions, [p.name]: vs } } }))}
            />
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="extras-h">
        <h2 id="extras-h" className="card-title">
          Extra runs
        </h2>
        <p className="muted">Models run once each alongside the grid (data quality, reverse stress).</p>
        {plan.extras.length === 0 && <Empty title="This question has no extra runs" />}
        {plan.extras.map((extra, i) => {
          const es = specs[extra.model_id];
          return (
            <div key={i} className="extra">
              <label className="check extra-head">
                <input type="checkbox" checked={included[i]} onChange={(e) => setIncluded((xs) => xs.map((x, j) => (j === i ? e.target.checked : x)))} />
                <span className="mono">{extra.model_id}</span>
                {es && <span className="muted"> — {es.title}</span>}
              </label>
              {included[i] && es && es.params.length > 0 && (
                <div className="param-list nested">
                  {es.params.map((p) => (
                    <ParamRow
                      key={p.name}
                      p={p}
                      allowVary={false}
                      mode={p.name in extra.params ? "fixed" : "default"}
                      fixedValue={extra.params[p.name] ?? p.default}
                      values={[]}
                      onMode={(m) =>
                        setPlan((prev) => {
                          const extras = prev.extras.map((x, j) => {
                            if (j !== i) return x;
                            const params = { ...x.params };
                            if (m === "fixed") params[p.name] = p.default;
                            else delete params[p.name];
                            return { ...x, params };
                          });
                          return { ...prev, extras };
                        })
                      }
                      onFixed={(v) =>
                        setPlan((prev) => ({ ...prev, extras: prev.extras.map((x, j) => (j === i ? { ...x, params: { ...x.params, [p.name]: v } } : x)) }))
                      }
                      onValues={() => undefined}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </section>

      <section className="card" aria-labelledby="opts-h">
        <h2 id="opts-h" className="card-title">
          Run options
        </h2>
        <div className="form-grid">
          <label>
            Seed
            <input type="number" step={1} min={0} value={Number.isNaN(seed) ? "" : seed} onChange={(e) => setSeed(e.target.valueAsNumber)} />
          </label>
          <label>
            Maximum variations
            <input
              type="number"
              step={1}
              min={1}
              max={1000}
              value={Number.isNaN(plan.max_variations) ? "" : plan.max_variations}
              onChange={(e) => setPlan((prev) => ({ ...prev, max_variations: e.target.valueAsNumber }))}
            />
          </label>
        </div>
        <label className="toggle">
          <input type="checkbox" role="switch" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} aria-describedby="llm-help" />
          <span>Allow a language model to draft rubric rationales</span>
        </label>
        <p id="llm-help" className="small muted">
          Off by default. Drafts are checked by the number verifier; any number not found in the model outputs rejects the draft and the
          rule-based rationale is kept. Language models never produce figures.
        </p>
      </section>

      <aside className="card preview" aria-labelledby="preview-h" aria-live="polite">
        <h2 id="preview-h" className="card-title">
          Variation preview
        </h2>
        <p className="preview-count">
          <span className="big-num">{gridTotal + nExtras}</span> variations
        </p>
        <p className="small">
          {Object.entries(plan.grid.dimensions)
            .map(([k, v]) => `${v.length} ${k}`)
            .join(" × ") || "no varied parameters"}{" "}
          = <strong>{total}</strong> grid combination{total === 1 ? "" : "s"} (cartesian product)
          {effective !== null && effective < total && (
            <>
              , <strong>{effective}</strong> distinct after inapplicable parameters drop out
            </>
          )}
          {nExtras > 0 && ` + ${nExtras} extra run${nExtras > 1 ? "s" : ""}`}.
        </p>
        {hasAppliesWhen && (
          <p className="small muted">Parameters with an “applies when” condition are dropped where it is not met, which may reduce the count; the server's planner is authoritative.</p>
        )}
        {problems.length > 0 && (
          <div className="problems" role="alert">
            <p className="state-title">Fix before starting</p>
            <ul>
              {problems.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          </div>
        )}
        {error && <ErrorPanel error={error} title="The server rejected the run" />}
        <button type="submit" className="btn btn-primary btn-block" disabled={problems.length > 0 || submitting}>
          {submitting ? "Starting…" : "Start run"}
        </button>
        <button type="button" className="btn btn-link" onClick={() => { setPlan(structuredClone(info.default_plan)); setIncluded(info.default_plan.extras.map(() => true)); }}>
          Reset to default plan
        </button>
      </aside>
    </form>
  );
}

export function NewRun() {
  const { question } = useParams();
  const q = question as QuestionId;
  const { draft, setDraft } = useDraft();
  const valid = (QUESTION_IDS as readonly string[]).includes(q);
  const data = useAsync(async (api) => (valid ? Promise.all([api.questions(), api.models(q)]) : Promise.reject({ code: "not_found", message: `Unknown question '${question}'.`, details: {} })), [q]);
  const usable = draft && draft.question === q ? draft : null;
  const api = useApi();
  const [sampleError, setSampleError] = useState<ErrorBody | null>(null);

  useEffect(() => {
    if (!valid || usable) return;
    // Reached directly (e.g. reload): fall back to the sample dataset.
    let live = true;
    api.sample(q).then(
      async (dataset) => {
        const findings = await api.validateDataset(dataset).catch(() => []);
        if (live) setDraft({ question: q, dataset, source: "sample", findings });
      },
      (e) => live && setSampleError(toErrorBody(e)),
    );
    return () => {
      live = false;
    };
  }, [api, q, usable, valid, setDraft]);

  const info = data.status === "ready" ? data.data[0].find((x) => x.question === q) : undefined;

  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Questions</Link> <span aria-hidden="true">/</span> <span>New run</span>
      </nav>
      <header className="page-head">
        <p className="eyebrow">{valid ? questionTag(q) : "New run"}</p>
        <h1>{info?.title ?? "Configure a run"}</h1>
      </header>
      {data.status === "loading" && <Loading label="Loading the catalogue" />}
      {data.status === "error" && <ErrorPanel error={data.error} onRetry={data.reload} />}
      {sampleError && <ErrorPanel error={sampleError} title="Could not load the sample dataset" />}
      {data.status === "ready" && !info && <Empty title="Question not offered by the API" />}
      {data.status === "ready" && info && !usable && !sampleError && <Loading label="Loading the sample dataset" />}
      {data.status === "ready" && info && usable && (
        <>
          <section className="dataset-strip" aria-label="Dataset">
            <div>
              <p className="eyebrow">{usable.source === "sample" ? "Sample dataset" : `Uploaded · ${usable.fileName ?? ""}`}</p>
              <p className="dataset-name">{usable.dataset.name}</p>
              <p className="small muted">
                As of {usable.dataset.as_of} · {datasetSummary(usable.dataset)} ·{" "}
                {usable.findings.filter((f) => f.severity !== "info").length} validation warning(s)/error(s)
              </p>
            </div>
            <Link to="/" className="btn btn-secondary">
              Change dataset
            </Link>
          </section>
          {usable.dataset.synthetic && <SyntheticBanner />}
          <PlanEditor key={q} info={info} models={data.data[1]} dataset={usable.dataset} />
        </>
      )}
    </div>
  );
}
