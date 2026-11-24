/**
 * Mock mode (`VITE_MOCK=1`): an in-memory implementation of `RiskbotApi` that serves the contract fixtures
 * (synced into `src/mocks/fixtures` by `npm run sync:fixtures`). It simulates the run lifecycle
 * pending -> running -> awaiting_review on a timer, enforces the same state rules as the server
 * (Conflict / NotFound / ValidationFailed as ErrorBody), applies factor edits with the shared rating rules
 * and keeps an audit log, so every screen can be demonstrated without the backend.
 */
import { ApiError, type RiskbotApi } from "../api/client";
import * as D from "../api/decoders";
import type {
  AuditEvent,
  Dataset,
  DataQualityFinding,
  ErrorBody,
  ModelSpec,
  QuestionId,
  Report,
  ReviewSubmission,
  RunRecord,
  RunResult,
  RunStatus,
  Trace,
} from "../api/types";
import { overallRating, rate } from "../lib/rules";
import { deriveComparison } from "./derive";

import questionsJson from "./fixtures/questions.json";
import modelsJson from "./fixtures/models.json";
import contractVersionJson from "./fixtures/contract_version.json";
import sampleQ1 from "./fixtures/sample_q1_market.json";
import sampleQ2 from "./fixtures/sample_q2_balance_sheet.json";
import sampleQ3 from "./fixtures/sample_q3_transition.json";
import resultQ1 from "./fixtures/run_result_q1_market.json";
import resultQ2 from "./fixtures/run_result_q2_balance_sheet.json";
import resultQ3 from "./fixtures/run_result_q3_transition.json";
import reportQ1 from "./fixtures/report_q1_market.json";
import reportQ2 from "./fixtures/report_q2_balance_sheet.json";
import reportQ3 from "./fixtures/report_q3_transition.json";
import traceQ1 from "./fixtures/trace_q1_market.json";
import traceQ2 from "./fixtures/trace_q2_balance_sheet.json";
import traceQ3 from "./fixtures/trace_q3_transition.json";

const QUESTIONS = D.arrayOf(D.QuestionInfo)(questionsJson);
const MODELS = D.arrayOf(D.ModelSpec)(modelsJson);
const SAMPLES: Record<QuestionId, Dataset> = {
  q1_market: D.Dataset(sampleQ1),
  q2_balance_sheet: D.Dataset(sampleQ2),
  q3_transition: D.Dataset(sampleQ3),
};
const RESULTS: Record<QuestionId, RunResult> = {
  q1_market: D.RunResult(resultQ1),
  q2_balance_sheet: D.RunResult(resultQ2),
  q3_transition: D.RunResult(resultQ3),
};
const REPORTS: Record<QuestionId, Report> = {
  q1_market: D.Report(reportQ1),
  q2_balance_sheet: D.Report(reportQ2),
  q3_transition: D.Report(reportQ3),
};
const TRACES: Trace[] = [D.Trace(traceQ1), D.Trace(traceQ2), D.Trace(traceQ3)];

interface MockRun {
  record: RunRecord;
  result: RunResult;
  startedAt: number;
  signoff: Report["signoff"];
  audit: AuditEvent[];
  failAfterRun: boolean;
}

export interface MockOptions {
  /** Milliseconds spent in `pending`, and three times this in `running`. 0 = settle immediately. */
  stepMs?: number;
  /** Artificial latency per call (ms). */
  latencyMs?: number;
  /** Pre-populate the three fixture runs (awaiting review). */
  seedRuns?: boolean;
  now?: () => number;
}

function fail(status: number, code: ErrorBody["code"], message: string, details: ErrorBody["details"] = {}): never {
  throw new ApiError(status, { code, message, details });
}

const clone = <A>(x: A): A => structuredClone(x);

export function createMockApi(opts: MockOptions = {}): RiskbotApi {
  const stepMs = opts.stepMs ?? 1200;
  const latency = opts.latencyMs ?? 120;
  const now = opts.now ?? (() => Date.now());
  const runs = new Map<string, MockRun>();
  let counter = 0;

  const iso = (ms = now()) => new Date(ms).toISOString();
  const delay = <A>(fn: () => A): Promise<A> =>
    new Promise((resolve, reject) => {
      const go = () => {
        try {
          resolve(fn());
        } catch (e) {
          reject(e);
        }
      };
      if (latency > 0) setTimeout(go, latency);
      else queueMicrotask(go);
    });

  const specFor = (modelId: string): ModelSpec | undefined => MODELS.find((m) => m.model_id === modelId);

  function log(run: MockRun, actor: string, event: string, detail: AuditEvent["detail"] = {}) {
    run.audit.push({ run_id: run.record.run_id, at: iso(), actor, event, detail });
  }

  function transition(run: MockRun, to: RunStatus) {
    const from = run.record.status;
    if (to === "awaiting_review") log(run, "system", "variations_executed", { n_variations: run.record.n_variations });
    run.record = { ...run.record, status: to, updated_at: iso(), error: to === "failed" ? "No grid variation succeeded (simulated failure)." : null };
    log(run, "system", "status_changed", { from, to });
  }

  /** Advance the simulated lifecycle based on elapsed time. */
  function tick(run: MockRun) {
    const st = run.record.status;
    if (st !== "pending" && st !== "running") return;
    const elapsed = now() - run.startedAt;
    const target: RunStatus =
      elapsed >= stepMs * 4 ? (run.failAfterRun ? "failed" : "awaiting_review") : elapsed >= stepMs ? "running" : "pending";
    if (target === st) return;
    if (st === "pending" && target !== "running") transition(run, "running");
    transition(run, target);
  }

  function getMockRun(runId: string): MockRun {
    const run = runs.get(runId);
    if (!run) fail(404, "not_found", `unknown run '${runId}'`);
    tick(run);
    return run;
  }

  function makeRun(question: QuestionId, dataset: Dataset, plan: RunResult["plan"] | null, settled: boolean, id?: string): MockRun {
    const base = RESULTS[question];
    const runId = id ?? `mock-${String(++counter).padStart(4, "0")}`;
    const created = now();
    const usedPlan = plan ?? base.plan;
    const record: RunRecord = {
      ...base.run,
      run_id: runId,
      status: settled ? "awaiting_review" : "pending",
      created_at: iso(created),
      updated_at: iso(created),
      dataset_name: dataset.name,
      synthetic: dataset.synthetic,
      contract_version: "mock",
      n_variations: base.variations.length,
    };
    const result: RunResult = {
      ...clone(base),
      run: record,
      plan: clone(usedPlan),
      comparison: deriveComparison(base.comparison, usedPlan, base.variations, specFor(usedPlan.grid.model_id)),
    };
    const run: MockRun = {
      record,
      result,
      startedAt: settled ? created - stepMs * 10 : created,
      signoff: null,
      audit: [],
      failAfterRun: dataset.name.toLowerCase().includes("fail"),
    };
    log(run, "system", "run_created", { question, dataset: dataset.name, plan_supplied: plan !== null });
    if (settled) log(run, "system", "status_changed", { from: "running", to: "awaiting_review" });
    runs.set(runId, run);
    return run;
  }

  if (opts.seedRuns ?? true) {
    for (const q of Object.keys(RESULTS) as QuestionId[]) {
      makeRun(q, SAMPLES[q], null, true, RESULTS[q].run.run_id);
    }
  }

  function validate(dataset: unknown): DataQualityFinding[] {
    let ds: Dataset;
    try {
      ds = D.Dataset(dataset);
    } catch (e) {
      fail(422, "validation_failed", e instanceof Error ? e.message : "invalid dataset");
    }
    const findings: DataQualityFinding[] = [];
    if (ds.synthetic) findings.push({ check: "synthetic_data", severity: "info", field: "synthetic", subject: null, count: 0, message: "Dataset is synthetic (generated), not real data." });
    if (ds.kind === "market") {
      for (const [ticker, series] of Object.entries(ds.returns)) {
        const missing = series.filter((x) => x === null).length;
        if (missing) findings.push({ check: "missing_returns", severity: "warning", field: `returns.${ticker}`, subject: ticker, count: missing, message: `${missing} missing return value(s) for ${ticker}.` });
      }
      if (ds.dates.length < 250) findings.push({ check: "short_history", severity: "warning", field: "dates", subject: null, count: ds.dates.length, message: `Only ${ds.dates.length} days of history; 250-day windows will use all of it.` });
    } else if (ds.kind === "climate") {
      const missing = ds.holdings.filter((h) => h.scope1 === null || h.scope2 === null);
      if (missing.length) findings.push({ check: "missing_scope12", severity: "warning", field: "holdings.scope1", subject: null, count: missing.length, message: `${missing.length} holding(s) without scope 1-2 emissions; they will be imputed.` });
      const noQ = ds.holdings.filter((h) => h.data_quality === null).length;
      if (noQ) findings.push({ check: "missing_data_quality", severity: "info", field: "holdings.data_quality", subject: null, count: noQ, message: `${noQ} holding(s) without a data-quality score.` });
    } else {
      const loans = ds.assets.filter((a) => a.kind === "loans").reduce((s, a) => s + a.book_value, 0);
      const ead = ds.loan_pools.reduce((s, p) => s + p.ead, 0);
      if (loans > 0 && Math.abs(ead - loans) / loans > 0.02) findings.push({ check: "loan_reconciliation", severity: "warning", field: "loan_pools", subject: null, count: 0, message: "Loan-pool EAD does not reconcile to the loan book within 2%." });
      if (ds.hedges.length === 0) findings.push({ check: "no_hedges", severity: "info", field: "hedges", subject: null, count: 0, message: "No interest-rate hedges recorded." });
    }
    findings.push({ check: "mock_mode", severity: "info", field: "dataset", subject: null, count: 0, message: "Validated in mock mode (subset of server checks)." });
    return findings;
  }

  function review(runId: string, sub: ReviewSubmission): RunRecord {
    let parsed: ReviewSubmission;
    try {
      parsed = D.ReviewSubmission(sub);
    } catch (e) {
      fail(422, "validation_failed", e instanceof Error ? e.message : "invalid review");
    }
    if (!parsed.reviewer.trim()) fail(422, "validation_failed", "reviewer must not be empty");
    const run = getMockRun(runId);
    if (run.record.status !== "awaiting_review") fail(409, "conflict", `run ${runId} is ${run.record.status}, not awaiting_review`);
    const at = iso();
    const assessment = clone(run.result.assessment);
    for (const edit of parsed.factor_edits ?? []) {
      if (!edit.reason.trim()) fail(422, "validation_failed", `factor edit for ${edit.factor_id} needs a reason`);
      const f = assessment.factors.find((x) => x.factor_id === edit.factor_id);
      if (!f) fail(422, "validation_failed", `unknown factor '${edit.factor_id}'`);
      for (const field of ["likelihood", "impact", "control", "rationale"] as const) {
        const value = edit[field];
        if (value === undefined || value === null || value === f[field]) continue;
        assessment.overrides.push({ factor_id: f.factor_id, field, old: f[field], new: value, reason: edit.reason, by: parsed.reviewer, at });
        (f as unknown as Record<string, unknown>)[field] = value;
      }
      [f.inherent, f.residual] = rate(f.likelihood, f.impact, f.control);
      f.source = "analyst";
      log(run, parsed.reviewer, "factor_edited", { factor_id: f.factor_id, reason: edit.reason });
    }
    assessment.overall = overallRating(assessment.factors.map((f) => f.residual));
    const status: RunStatus = parsed.decision === "approve" ? "approved" : "rejected";
    run.record = { ...run.record, status, updated_at: at };
    run.result = { ...run.result, run: run.record, assessment };
    run.signoff = { reviewer: parsed.reviewer, decision: parsed.decision, comment: parsed.comment ?? "", at };
    log(run, parsed.reviewer, "review_submitted", { decision: parsed.decision, comment: parsed.comment ?? "" });
    log(run, "system", "report_generated", {});
    return clone(run.record);
  }

  function requireResult(run: MockRun) {
    const st = run.record.status;
    if (st === "pending" || st === "running" || st === "failed") fail(409, "conflict", `run ${run.record.run_id} is ${st}`);
  }

  function report(runId: string): Report {
    const run = getMockRun(runId);
    requireResult(run);
    const base = REPORTS[run.record.question];
    const headline = base.headline;
    const so = run.signoff;
    const markdown = [
      base.markdown.replace(/^# Run \S+/, `# Run ${runId}`),
      "",
      "## Headline",
      "",
      ...headline.map((h) => `- ${h}`),
      "",
      "## Sign-off",
      "",
      so ? `**${so.decision === "approve" ? "Approved" : "Rejected"}** by ${so.reviewer} at ${so.at}.${so.comment ? ` Comment: ${so.comment}` : ""}` : "_Awaiting review._",
      "",
      run.record.synthetic ? "> Sample data is synthetic." : "",
    ].join("\n");
    return clone({ run: run.record, headline, comparison: run.result.comparison, assessment: run.result.assessment, signoff: so, markdown });
  }

  function trace(traceId: string): Trace {
    for (const run of runs.values()) {
      for (const v of run.result.variations) {
        const t = v.output?.traces.find((x) => x.trace_id === traceId);
        if (t) return clone(t);
      }
    }
    const t = TRACES.find((x) => x.trace_id === traceId);
    if (t) return clone(t);
    fail(404, "not_found", `unknown trace '${traceId}'`);
  }

  return {
    mode: "mock",
    baseUrl: "mock://fixtures",
    health: () => delay(() => ({ status: "ok", contract_version: contractVersionJson.contract_version })),
    questions: () => delay(() => clone(QUESTIONS)),
    models: (q) => delay(() => clone(q ? MODELS.filter((m) => m.question === q) : MODELS)),
    sample: (q) =>
      delay(() => {
        if (!(q in SAMPLES)) fail(404, "not_found", `unknown question '${q}'`);
        return clone(SAMPLES[q]);
      }),
    validateDataset: (ds) => delay(() => validate(ds)),
    calc: (req) =>
      delay(() => {
        const r = RESULTS[MODELS.find((m) => m.model_id === req.model_id)?.question ?? "q1_market"];
        const v = r.variations.find((x) => x.spec.model_id === req.model_id && x.output);
        if (!v?.output) fail(404, "not_found", `unknown model '${req.model_id}'`);
        return clone(v.output);
      }),
    startRun: (req) =>
      delay(() => {
        let parsed;
        try {
          parsed = D.RunRequest(req);
        } catch (e) {
          fail(422, "validation_failed", e instanceof Error ? e.message : "invalid run request");
        }
        if (parsed.plan && parsed.plan.question !== parsed.question) fail(422, "validation_failed", "plan.question does not match request.question");
        const run = makeRun(parsed.question, parsed.dataset, parsed.plan ?? null, stepMs === 0);
        if (parsed.use_llm) log(run, "system", "llm_enabled", { note: "mock mode: no LLM is called" });
        return clone(run.record);
      }),
    listRuns: (limit = 20) =>
      delay(() =>
        [...runs.values()]
          .map((r) => (tick(r), r.record))
          .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.run_id.localeCompare(a.run_id))
          .slice(0, limit)
          .map(clone),
      ),
    getRun: (id) => delay(() => clone(getMockRun(id).record)),
    getResult: (id) =>
      delay(() => {
        const run = getMockRun(id);
        requireResult(run);
        return clone({ ...run.result, run: run.record });
      }),
    getAudit: (id) => delay(() => clone(getMockRun(id).audit)),
    submitReview: (id, sub) => delay(() => review(id, sub)),
    getReport: (id) => delay(() => report(id)),
    getTrace: (id) => delay(() => trace(id)),
  };
}
