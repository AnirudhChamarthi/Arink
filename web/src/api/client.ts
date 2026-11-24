/**
 * Typed client for the Riskbot REST API (CONTRACT.md section 6.1).
 *
 * Every response is decoded by the contract decoders, so a shape mismatch surfaces as a readable error
 * instead of a broken screen. Errors from the server are parsed as `ErrorBody` and thrown as `ApiError`.
 * The mock implementation (`src/mocks/mockApi.ts`) satisfies the same `RiskbotApi` interface.
 */
import * as D from "./decoders";
import type {
  AuditEvent,
  Dataset,
  DataQualityFinding,
  ErrorBody,
  Health,
  ModelOutput,
  ModelSpec,
  QuestionId,
  QuestionInfo,
  CalcRequest,
  Report,
  ReviewSubmission,
  RunRecord,
  RunRequest,
  RunResult,
  RunStatus,
  Trace,
} from "./types";
import { SETTLED_STATUSES } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorBody,
  ) {
    super(body.message);
    this.name = "ApiError";
  }
  get code() {
    return this.body.code;
  }
}

export interface RiskbotApi {
  readonly mode: "http" | "mock";
  readonly baseUrl: string;
  health(): Promise<Health>;
  questions(): Promise<QuestionInfo[]>;
  models(question?: QuestionId): Promise<ModelSpec[]>;
  sample(question: QuestionId): Promise<Dataset>;
  validateDataset(dataset: Dataset): Promise<DataQualityFinding[]>;
  calc(request: CalcRequest): Promise<ModelOutput>;
  startRun(request: RunRequest): Promise<RunRecord>;
  listRuns(limit?: number): Promise<RunRecord[]>;
  getRun(runId: string): Promise<RunRecord>;
  getResult(runId: string): Promise<RunResult>;
  getAudit(runId: string): Promise<AuditEvent[]>;
  submitReview(runId: string, review: ReviewSubmission): Promise<RunRecord>;
  getReport(runId: string): Promise<Report>;
  getTrace(traceId: string): Promise<Trace>;
}

export const DEFAULT_API_BASE = "http://localhost:8000/v2";

const healthDecoder = D.object<Health>("Health", { status: D.withDefault(D.str, "ok"), contract_version: D.str });

/** Convert any thrown value into an ErrorBody for display. */
export function toErrorBody(err: unknown): ErrorBody {
  if (err instanceof ApiError) return err.body;
  if (err instanceof D.DecodeError) return { code: "internal", message: err.message, details: { path: err.path } };
  if (err instanceof Error) return { code: "internal", message: err.message, details: {} };
  return { code: "internal", message: String(err), details: {} };
}

export function createHttpApi(baseUrl: string = DEFAULT_API_BASE, fetchImpl: typeof fetch = (...a) => fetch(...a)): RiskbotApi {
  const base = baseUrl.replace(/\/+$/, "");

  async function request<A>(method: "GET" | "POST", path: string, decode: D.Decoder<A>, body?: unknown): Promise<A> {
    let res: Response;
    try {
      res = await fetchImpl(`${base}${path}`, {
        method,
        headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new ApiError(0, {
        code: "internal",
        message: `Cannot reach the Riskbot API at ${base} (${e instanceof Error ? e.message : String(e)}).`,
        details: {},
      });
    }
    const text = await res.text();
    let payload: unknown = undefined;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = undefined;
      }
    }
    if (!res.ok) {
      if (D.isErrorBody(payload)) throw new ApiError(res.status, D.ErrorBody(payload));
      // FastAPI's own 422 body ({"detail": [...]}) or a proxy error page.
      const detail = payload && typeof payload === "object" && "detail" in payload ? (payload as { detail: unknown }).detail : undefined;
      throw new ApiError(res.status, {
        code: res.status === 404 ? "not_found" : res.status === 409 ? "conflict" : res.status === 422 ? "validation_failed" : "internal",
        message: typeof detail === "string" ? detail : `HTTP ${res.status} ${res.statusText || ""}`.trim(),
        details: detail !== undefined && typeof detail !== "string" ? { detail: detail as never } : {},
      });
    }
    return decode(payload);
  }

  const enc = encodeURIComponent;
  return {
    mode: "http",
    baseUrl: base,
    health: () => request("GET", "/health", healthDecoder),
    questions: () => request("GET", "/questions", D.arrayOf(D.QuestionInfo)),
    models: (q) => request("GET", q ? `/models?question=${enc(q)}` : "/models", D.arrayOf(D.ModelSpec)),
    sample: (q) => request("GET", `/samples/${enc(q)}`, D.Dataset),
    validateDataset: (ds) => request("POST", "/datasets/validate", D.arrayOf(D.DataQualityFinding), ds),
    calc: (req) => request("POST", "/calc", D.ModelOutput, req),
    startRun: (req) => request("POST", "/runs", D.RunRecord, req),
    listRuns: (limit = 20) => request("GET", `/runs?limit=${limit}`, D.arrayOf(D.RunRecord)),
    getRun: (id) => request("GET", `/runs/${enc(id)}`, D.RunRecord),
    getResult: (id) => request("GET", `/runs/${enc(id)}/result`, D.RunResult),
    getAudit: (id) => request("GET", `/runs/${enc(id)}/audit`, D.arrayOf(D.AuditEvent)),
    submitReview: (id, review) => request("POST", `/runs/${enc(id)}/review`, D.RunRecord, review),
    getReport: (id) => request("GET", `/runs/${enc(id)}/report`, D.Report),
    getTrace: (id) => request("GET", `/traces/${enc(id)}`, D.Trace),
  };
}

export const POLL_INTERVAL_MS = 1500;

export function isSettled(status: RunStatus): boolean {
  return SETTLED_STATUSES.includes(status);
}

export interface PollOptions {
  intervalMs?: number;
  signal?: AbortSignal;
  onUpdate?: (run: RunRecord) => void;
}

/**
 * Poll `GET /runs/{id}` until the run reaches awaiting_review, approved, rejected or failed.
 * Resolves with the settled record; rejects on an API error or when aborted.
 */
export async function pollRun(api: RiskbotApi, runId: string, opts: PollOptions = {}): Promise<RunRecord> {
  const interval = opts.intervalMs ?? POLL_INTERVAL_MS;
  for (;;) {
    if (opts.signal?.aborted) throw new DOMException("Polling aborted", "AbortError");
    const run = await api.getRun(runId);
    opts.onUpdate?.(run);
    if (isSettled(run.status)) return run;
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, interval);
      opts.signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(t);
          reject(new DOMException("Polling aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}
