/**
 * Runtime decoders (guards) for every contract type.
 *
 * Each decoder checks the shape of untrusted JSON and returns it typed. Like the pydantic models they
 * mirror, object decoders reject unknown fields ("fail loudly at boundaries") and fill documented
 * defaults when a field is absent. Object decoders record their field list so the contract test can
 * compare it with the JSON Schema; their shapes are typed against `types.ts`, so `tsc` catches drift on
 * the TypeScript side.
 */
import * as T from "./types";

export class DecodeError extends Error {
  constructor(
    readonly path: string,
    readonly problem: string,
  ) {
    super(`Unexpected response shape at ${path || "<root>"}: ${problem}`);
    this.name = "DecodeError";
  }
}

export interface Decoder<A> {
  (value: unknown, path?: string): A;
  /** Field names, for object decoders. */
  fields?: readonly string[];
  /** Field decoders, for object decoders. */
  shape?: Readonly<Record<string, Decoder<unknown>>>;
  /** Value used when the field is absent from an object. */
  fallback?: () => A;
  /** Field may be absent (request types). */
  optional?: boolean;
}

function make<A>(fn: (value: unknown, path: string) => A): Decoder<A> {
  return ((value: unknown, path = "") => fn(value, path)) as Decoder<A>;
}

const describe = (v: unknown) => (v === null ? "null" : Array.isArray(v) ? "array" : typeof v);
const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export const str = make<string>((v, p) => {
  if (typeof v !== "string") throw new DecodeError(p, `expected string, got ${describe(v)}`);
  return v;
});

export const num = make<number>((v, p) => {
  if (typeof v !== "number" || Number.isNaN(v)) throw new DecodeError(p, `expected number, got ${describe(v)}`);
  return v;
});

export const int = make<number>((v, p) => {
  if (typeof v !== "number" || !Number.isInteger(v)) throw new DecodeError(p, `expected integer, got ${describe(v)}`);
  return v;
});

export const bool = make<boolean>((v, p) => {
  if (typeof v !== "boolean") throw new DecodeError(p, `expected boolean, got ${describe(v)}`);
  return v;
});

export const json = make<T.Json>((v, p) => {
  const ok = (x: unknown): boolean =>
    x === null ||
    typeof x === "string" ||
    typeof x === "boolean" ||
    (typeof x === "number" && Number.isFinite(x)) ||
    (Array.isArray(x) && x.every(ok)) ||
    (isPlainObject(x) && Object.values(x).every(ok));
  if (!ok(v)) throw new DecodeError(p, "expected JSON value");
  return v as T.Json;
});

export function oneOf<const V extends readonly (string | number | boolean)[]>(values: V): Decoder<V[number]> {
  return make((v, p) => {
    if (!values.includes(v as V[number])) {
      throw new DecodeError(p, `expected one of ${values.map((x) => JSON.stringify(x)).join(", ")}, got ${JSON.stringify(v)}`);
    }
    return v as V[number];
  });
}

export function nullable<A>(d: Decoder<A>): Decoder<A | null> {
  return make((v, p) => (v === null ? null : d(v, p)));
}

export function arrayOf<A>(d: Decoder<A>): Decoder<A[]> {
  return make((v, p) => {
    if (!Array.isArray(v)) throw new DecodeError(p, `expected array, got ${describe(v)}`);
    return v.map((x, i) => d(x, `${p}[${i}]`));
  });
}

export function record<A>(d: Decoder<A>): Decoder<Record<string, A>> {
  return make((v, p) => {
    if (!isPlainObject(v)) throw new DecodeError(p, `expected object, got ${describe(v)}`);
    const out: Record<string, A> = {};
    for (const [k, x] of Object.entries(v)) out[k] = d(x, `${p}.${k}`);
    return out;
  });
}

/** Field with a server-side default: filled in when absent. */
export function withDefault<A>(d: Decoder<A>, value: A): Decoder<A> {
  const out = make(d);
  out.fallback = () => structuredClone(value);
  return out;
}

/** Field that may be absent (request types only). */
export function optional<A>(d: Decoder<A>): Decoder<A | undefined> {
  const out = make<A | undefined>((v, p) => (v === undefined ? undefined : d(v, p)));
  out.optional = true;
  return out;
}

type Shape<A> = { [K in keyof A]-?: Decoder<A[K]> };

export function object<A>(name: string, shape: Shape<A>): Decoder<A> {
  const keys = Object.keys(shape) as (keyof A & string)[];
  const out = make<A>((v, p) => {
    if (!isPlainObject(v)) throw new DecodeError(p || name, `expected ${name} object, got ${describe(v)}`);
    const unknown = Object.keys(v).filter((k) => !(k in shape));
    if (unknown.length) throw new DecodeError(p || name, `unknown field(s) ${unknown.join(", ")} in ${name}`);
    const result = {} as A;
    for (const k of keys) {
      const d = shape[k] as Decoder<unknown>;
      const fieldPath = p ? `${p}.${k}` : `${name}.${k}`;
      if (!(k in v) || v[k] === undefined) {
        if (d.fallback) (result as Record<string, unknown>)[k] = d.fallback();
        else if (!d.optional) throw new DecodeError(fieldPath, "missing required field");
        continue;
      }
      (result as Record<string, unknown>)[k] = d(v[k], fieldPath);
    }
    return result;
  });
  out.fields = keys;
  out.shape = shape as Record<string, Decoder<unknown>>;
  return out;
}

// ------------------------------------------------------------------------------------------------
// Contract types
// ------------------------------------------------------------------------------------------------

const questionId = oneOf(T.QUESTION_IDS);
const datasetKind = oneOf(T.DATASET_KINDS);
const unit = oneOf(T.UNITS);
const severity = oneOf(T.SEVERITIES);
const rating = oneOf(T.RATINGS);
const control = oneOf(T.CONTROL_STRENGTHS);
const tableCell = make<T.TableCell>((v, p) => {
  if (v === null || ["number", "string", "boolean"].includes(typeof v)) return v as T.TableCell;
  throw new DecodeError(p, `expected table cell, got ${describe(v)}`);
});
const params = record(json);

export const TraceStep = object<T.TraceStep>("TraceStep", {
  id: str,
  title: str,
  formula: str,
  substitution: str,
  value: withDefault(nullable(num), null),
  unit: withDefault(nullable(unit), null),
  table: withDefault(nullable(arrayOf(record(tableCell))), null),
  note: withDefault(str, ""),
});

export const Trace = object<T.Trace>("Trace", {
  trace_id: str,
  model_id: str,
  title: str,
  assumptions: arrayOf(str),
  inputs: record(json),
  steps: arrayOf(TraceStep),
  result: record(num),
  input_hash: str,
  warnings: withDefault(arrayOf(str), []),
});

export const DataQualityFinding = object<T.DataQualityFinding>("DataQualityFinding", {
  check: str,
  severity,
  field: str,
  subject: withDefault(nullable(str), null),
  count: withDefault(int, 0),
  message: str,
});

export const MarketPosition = object<T.MarketPosition>("MarketPosition", {
  ticker: str,
  asset_class: withDefault(oneOf(["equity", "fixed_income", "commodity", "cash", "other"] as const), "equity"),
  sector: withDefault(nullable(str), null),
  quantity: num,
  price: num,
  currency: withDefault(str, "USD"),
});

export const MarketDataset = object<T.MarketDataset>("MarketDataset", {
  kind: withDefault(oneOf(["market"] as const), "market"),
  name: str,
  base_currency: withDefault(str, "USD"),
  as_of: str,
  synthetic: bool,
  positions: arrayOf(MarketPosition),
  dates: arrayOf(str),
  returns: record(arrayOf(nullable(num))),
});

export const BsAsset = object<T.BsAsset>("BsAsset", {
  id: str,
  kind: oneOf(["cash", "hqla_securities", "afs_securities", "htm_securities", "loans", "other"] as const),
  book_value: num,
  market_value: num,
  coupon_rate: num,
  maturity_years: num,
  repricing_years: num,
  modified_duration: withDefault(nullable(num), null),
  convexity: withDefault(nullable(num), null),
  hqla_level: withDefault(nullable(oneOf(["1", "2a", "2b"] as const)), null),
});

export const LoanPool = object<T.LoanPool>("LoanPool", {
  segment: str,
  ead: num,
  pd: num,
  lgd: num,
  asset_correlation: num,
});

export const DepositSegment = object<T.DepositSegment>("DepositSegment", {
  segment: str,
  balance: num,
  insured_share: num,
  rate_beta: num,
  runoff_slow: num,
  runoff_fast: num,
  rate: withDefault(num, 0),
});

export const WholesaleFunding = object<T.WholesaleFunding>("WholesaleFunding", {
  id: str,
  amount: num,
  maturity_days: int,
  rate: num,
});

export const SwapHedge = object<T.SwapHedge>("SwapHedge", {
  id: str,
  notional: num,
  fixed_rate: num,
  maturity_years: num,
  pay_fixed: withDefault(bool, true),
});

const governanceValue = make<number | string | boolean>((v, p) => {
  if (["number", "string", "boolean"].includes(typeof v)) return v as number | string | boolean;
  throw new DecodeError(p, `expected number, string or boolean, got ${describe(v)}`);
});

export const BankBalanceSheet = object<T.BankBalanceSheet>("BankBalanceSheet", {
  kind: withDefault(oneOf(["balance_sheet"] as const), "balance_sheet"),
  name: str,
  as_of: str,
  currency: withDefault(str, "USD"),
  synthetic: bool,
  assets: arrayOf(BsAsset),
  loan_pools: arrayOf(LoanPool),
  deposits: arrayOf(DepositSegment),
  wholesale_funding: withDefault(arrayOf(WholesaleFunding), []),
  hedges: withDefault(arrayOf(SwapHedge), []),
  cet1_capital: num,
  risk_weighted_assets: num,
  policy_rate: num,
  governance: withDefault(record(governanceValue), {}),
});

export const ClimateHolding = object<T.ClimateHolding>("ClimateHolding", {
  issuer: str,
  sector: str,
  market_value: num,
  evic: num,
  revenue: num,
  ebitda: withDefault(nullable(num), null),
  scope1: withDefault(nullable(num), null),
  scope2: withDefault(nullable(num), null),
  scope3: withDefault(nullable(num), null),
  data_quality: withDefault(nullable(int), null),
  emissions_year: withDefault(nullable(int), null),
  controversy_flags: withDefault(arrayOf(str), []),
  exclusion_flags: withDefault(arrayOf(str), []),
});

export const ClimatePortfolio = object<T.ClimatePortfolio>("ClimatePortfolio", {
  kind: withDefault(oneOf(["climate"] as const), "climate"),
  name: str,
  as_of: str,
  currency: withDefault(str, "USD"),
  synthetic: bool,
  holdings: arrayOf(ClimateHolding),
});

/** Discriminated on `kind`, as in the contract. */
export const Dataset = make<T.Dataset>((v, p) => {
  const kind = isPlainObject(v) ? v.kind : undefined;
  if (kind === "market") return MarketDataset(v, p);
  if (kind === "balance_sheet") return BankBalanceSheet(v, p);
  if (kind === "climate") return ClimatePortfolio(v, p);
  throw new DecodeError(p ? `${p}.kind` : "Dataset.kind", `expected "market", "balance_sheet" or "climate", got ${JSON.stringify(kind)}`);
});

export const ParamSpec = object<T.ParamSpec>("ParamSpec", {
  name: str,
  type: oneOf(["float", "int", "str", "bool"] as const),
  default: withDefault(json, null),
  choices: withDefault(nullable(arrayOf(json)), null),
  minimum: withDefault(nullable(num), null),
  maximum: withDefault(nullable(num), null),
  applies_when: withDefault(nullable(record(arrayOf(json))), null),
  description: str,
});

export const MetricSpec = object<T.MetricSpec>("MetricSpec", {
  key: str,
  unit,
  description: str,
  higher_is_worse: withDefault(nullable(bool), null),
  optional: withDefault(bool, false),
});

export const ModelSpec = object<T.ModelSpec>("ModelSpec", {
  model_id: str,
  question: questionId,
  dataset_kind: datasetKind,
  title: str,
  description: str,
  params: arrayOf(ParamSpec),
  metrics: arrayOf(MetricSpec),
  labels: withDefault(record(arrayOf(str)), {}),
  method_param: withDefault(nullable(str), null),
  pass_label: withDefault(nullable(str), null),
});

export const Metric = object<T.Metric>("Metric", {
  value: num,
  unit,
  trace_id: withDefault(nullable(str), null),
  trace_step: withDefault(nullable(str), null),
});

export const ModelOutput = object<T.ModelOutput>("ModelOutput", {
  model_id: str,
  params,
  metrics: record(Metric),
  labels: withDefault(record(str), {}),
  traces: arrayOf(Trace),
  findings: withDefault(arrayOf(DataQualityFinding), []),
  warnings: withDefault(arrayOf(str), []),
});

export const GridSpec = object<T.GridSpec>("GridSpec", {
  model_id: str,
  dimensions: record(arrayOf(json)),
  fixed: withDefault(params, {}),
});

export const ExtraRun = object<T.ExtraRun>("ExtraRun", {
  model_id: str,
  params: withDefault(params, {}),
});

export const QuestionPlan = object<T.QuestionPlan>("QuestionPlan", {
  question: questionId,
  grid: GridSpec,
  extras: withDefault(arrayOf(ExtraRun), []),
  max_variations: withDefault(int, 200),
});

export const VariationSpec = object<T.VariationSpec>("VariationSpec", {
  variation_id: str,
  question: questionId,
  model_id: str,
  params,
  seed: int,
  role: withDefault(oneOf(["grid", "extra"] as const), "grid"),
});

export const VariationResult = object<T.VariationResult>("VariationResult", {
  spec: VariationSpec,
  output: withDefault(nullable(ModelOutput), null),
  error: withDefault(nullable(str), null),
  duration_ms: num,
});

export const MetricRange = object<T.MetricRange>("MetricRange", {
  unit,
  min: num,
  median: num,
  max: num,
  n: int,
});

export const SensitivityRow = object<T.SensitivityRow>("SensitivityRow", {
  dimension: str,
  metric: str,
  medians: record(num),
  effect: num,
});

export const ConclusionFlip = object<T.ConclusionFlip>("ConclusionFlip", {
  label: str,
  dimension: str,
  from_value: str,
  to_value: str,
  outcome_from: str,
  outcome_to: str,
  description: str,
});

export const BreakEven = object<T.BreakEven>("BreakEven", {
  name: str,
  value: nullable(num),
  unit,
  found: bool,
  trace_id: withDefault(nullable(str), null),
  description: str,
});

export const Comparison = object<T.Comparison>("Comparison", {
  question: questionId,
  metric_ranges: record(MetricRange),
  method_spread: withDefault(record(num), {}),
  sensitivity: withDefault(arrayOf(SensitivityRow), []),
  flips: withDefault(arrayOf(ConclusionFlip), []),
  break_evens: withDefault(arrayOf(BreakEven), []),
  label_counts: withDefault(record(record(int)), {}),
});

export const Evidence = object<T.Evidence>("Evidence", {
  kind: oneOf(T.EVIDENCE_KINDS),
  ref: str,
  description: str,
});

export const QualitativeFactor = object<T.QualitativeFactor>("QualitativeFactor", {
  factor_id: str,
  name: str,
  description: str,
  likelihood: int,
  impact: int,
  control,
  inherent: rating,
  residual: rating,
  evidence: withDefault(arrayOf(Evidence), []),
  rationale: str,
  source: oneOf(T.FACTOR_SOURCES),
});

export const Override = object<T.Override>("Override", {
  factor_id: str,
  field: str,
  old: json,
  new: json,
  reason: str,
  by: str,
  at: str,
});

export const QualitativeAssessment = object<T.QualitativeAssessment>("QualitativeAssessment", {
  question: questionId,
  label: withDefault(oneOf(["judgment"] as const), "judgment"),
  factors: arrayOf(QualitativeFactor),
  overall: rating,
  overrides: withDefault(arrayOf(Override), []),
  method_note: str,
});

export const RunRecord = object<T.RunRecord>("RunRecord", {
  run_id: str,
  question: questionId,
  status: oneOf(T.RUN_STATUSES),
  created_at: str,
  updated_at: str,
  input_hash: str,
  contract_version: str,
  n_variations: int,
  dataset_name: str,
  synthetic: bool,
  error: withDefault(nullable(str), null),
});

export const VerifierFinding = object<T.VerifierFinding>("VerifierFinding", {
  location: str,
  text: str,
  value: nullable(num),
  matched: bool,
  message: str,
});

export const RunResult = object<T.RunResult>("RunResult", {
  run: RunRecord,
  plan: QuestionPlan,
  variations: arrayOf(VariationResult),
  comparison: Comparison,
  assessment: QualitativeAssessment,
  verifier_findings: withDefault(arrayOf(VerifierFinding), []),
});

export const RunRequest = object<T.RunRequest>("RunRequest", {
  question: questionId,
  dataset: Dataset,
  plan: optional(nullable(QuestionPlan)),
  seed: optional(int),
  use_llm: optional(bool),
});

export const FactorEdit = object<T.FactorEdit>("FactorEdit", {
  factor_id: str,
  likelihood: optional(nullable(int)),
  impact: optional(nullable(int)),
  control: optional(nullable(control)),
  rationale: optional(nullable(str)),
  reason: str,
});

export const ReviewSubmission = object<T.ReviewSubmission>("ReviewSubmission", {
  decision: oneOf(T.REVIEW_DECISIONS),
  reviewer: str,
  comment: optional(str),
  factor_edits: optional(arrayOf(FactorEdit)),
});

export const SignOff = object<T.SignOff>("SignOff", {
  reviewer: str,
  decision: oneOf(T.REVIEW_DECISIONS),
  comment: str,
  at: str,
});

export const AuditEvent = object<T.AuditEvent>("AuditEvent", {
  run_id: str,
  at: str,
  actor: str,
  event: str,
  detail: withDefault(record(json), {}),
});

export const Report = object<T.Report>("Report", {
  run: RunRecord,
  headline: arrayOf(str),
  comparison: Comparison,
  assessment: QualitativeAssessment,
  signoff: withDefault(nullable(SignOff), null),
  markdown: str,
});

export const CalcRequest = object<T.CalcRequest>("CalcRequest", {
  model_id: str,
  dataset: Dataset,
  params: optional(params),
  seed: optional(int),
});

export const QuestionInfo = object<T.QuestionInfo>("QuestionInfo", {
  question: questionId,
  title: str,
  description: str,
  dataset_kind: datasetKind,
  default_plan: QuestionPlan,
});

export const ErrorBody = object<T.ErrorBody>("ErrorBody", {
  code: oneOf(T.ERROR_CODES),
  message: str,
  details: withDefault(record(json), {}),
});

/** Object decoders by contract type name (used by the schema drift test). */
export const OBJECT_DECODERS: Record<string, Decoder<unknown>> = {
  TraceStep, Trace, DataQualityFinding, MarketPosition, MarketDataset, BsAsset, LoanPool, DepositSegment,
  WholesaleFunding, SwapHedge, BankBalanceSheet, ClimateHolding, ClimatePortfolio, ParamSpec, MetricSpec,
  ModelSpec, Metric, ModelOutput, GridSpec, ExtraRun, QuestionPlan, VariationSpec, VariationResult,
  MetricRange, SensitivityRow, ConclusionFlip, BreakEven, Comparison, Evidence, QualitativeFactor, Override,
  QualitativeAssessment, RunRecord, VerifierFinding, RunResult, RunRequest, FactorEdit, ReviewSubmission,
  SignOff, AuditEvent, Report, CalcRequest, QuestionInfo, ErrorBody,
};

/** Non-throwing guard: true if `value` is an ErrorBody. */
export function isErrorBody(value: unknown): value is T.ErrorBody {
  try {
    ErrorBody(value);
    return true;
  } catch {
    return false;
  }
}
