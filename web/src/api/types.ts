/**
 * TypeScript mirror of the Riskbot v2 contract (`riskbot/contract/types.py`, contract 2.0.0).
 *
 * Hand-written to match `riskbot/contract/generated/schema/*.json` exactly. The chain that keeps them in
 * step is checked mechanically:
 *   - `decoders.ts` builds a runtime decoder per type whose shape is typed against these interfaces, so
 *     `tsc` fails if a field is missing or has the wrong type;
 *   - `contract.test.ts` checks that every decoder's field list equals the JSON Schema's property list
 *     and that every fixture validates against both the JSON Schema and the decoder.
 *
 * Response types list fields that have server-side defaults as required, because pydantic always
 * serialises them (the decoders fill the default if a server ever omits one). Request types keep them
 * optional.
 */

// ------------------------------------------------------------------------------------------------
// Enumerations
// ------------------------------------------------------------------------------------------------

export const QUESTION_IDS = ["q1_market", "q2_balance_sheet", "q3_transition"] as const;
export type QuestionId = (typeof QUESTION_IDS)[number];

export const DATASET_KINDS = ["market", "balance_sheet", "climate"] as const;
export type DatasetKind = (typeof DATASET_KINDS)[number];

export const UNITS = [
  "fraction_of_gross",
  "fraction",
  "currency",
  "bp",
  "count",
  "ratio",
  "probability",
  "tCO2e",
  "tCO2e_per_musd",
  "days",
  "years",
] as const;
export type Unit = (typeof UNITS)[number];

export const SEVERITIES = ["info", "warning", "error"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const RATINGS = ["low", "medium", "high", "critical"] as const;
export type Rating = (typeof RATINGS)[number];

export const CONTROL_STRENGTHS = ["weak", "adequate", "strong"] as const;
export type ControlStrength = (typeof CONTROL_STRENGTHS)[number];

export const FACTOR_SOURCES = ["rule", "llm_draft", "analyst", "unassessed"] as const;
export type FactorSource = (typeof FACTOR_SOURCES)[number];

export const RUN_STATUSES = ["pending", "running", "awaiting_review", "approved", "rejected", "failed"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

/** Statuses at which polling stops (the run will not change without a reviewer). */
export const SETTLED_STATUSES: readonly RunStatus[] = ["awaiting_review", "approved", "rejected", "failed"];

export const REVIEW_DECISIONS = ["approve", "reject"] as const;
export type ReviewDecision = (typeof REVIEW_DECISIONS)[number];

export const ERROR_CODES = ["not_found", "validation_failed", "conflict", "limit_exceeded", "internal"] as const;
export type ErrorCode = (typeof ERROR_CODES)[number];

export const EVIDENCE_KINDS = ["trace", "finding", "metric", "dataset_field", "note"] as const;
export type EvidenceKind = (typeof EVIDENCE_KINDS)[number];

/** Any JSON value (pydantic `Any`). */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
/** Parameter values used in plans and model outputs. */
export type ParamValue = Json;

// ------------------------------------------------------------------------------------------------
// Traces
// ------------------------------------------------------------------------------------------------

export type TableCell = number | string | boolean | null;

export interface TraceStep {
  id: string;
  title: string;
  /** LaTeX without surrounding $ delimiters. */
  formula: string;
  /** The formula with numbers filled in, plain text or LaTeX. */
  substitution: string;
  value: number | null;
  unit: Unit | null;
  table: Record<string, TableCell>[] | null;
  note: string;
}

export interface Trace {
  trace_id: string;
  model_id: string;
  title: string;
  assumptions: string[];
  inputs: Record<string, Json>;
  steps: TraceStep[];
  result: Record<string, number>;
  input_hash: string;
  warnings: string[];
}

// ------------------------------------------------------------------------------------------------
// Data quality
// ------------------------------------------------------------------------------------------------

export interface DataQualityFinding {
  check: string;
  severity: Severity;
  field: string;
  subject: string | null;
  count: number;
  message: string;
}

// ------------------------------------------------------------------------------------------------
// Datasets
// ------------------------------------------------------------------------------------------------

export interface MarketPosition {
  ticker: string;
  asset_class: "equity" | "fixed_income" | "commodity" | "cash" | "other";
  sector: string | null;
  quantity: number;
  price: number;
  currency: string;
}

export interface MarketDataset {
  kind: "market";
  name: string;
  base_currency: string;
  as_of: string;
  synthetic: boolean;
  positions: MarketPosition[];
  dates: string[];
  returns: Record<string, (number | null)[]>;
}

export interface BsAsset {
  id: string;
  kind: "cash" | "hqla_securities" | "afs_securities" | "htm_securities" | "loans" | "other";
  book_value: number;
  market_value: number;
  coupon_rate: number;
  maturity_years: number;
  repricing_years: number;
  modified_duration: number | null;
  convexity: number | null;
  hqla_level: "1" | "2a" | "2b" | null;
}

export interface LoanPool {
  segment: string;
  ead: number;
  pd: number;
  lgd: number;
  asset_correlation: number;
}

export interface DepositSegment {
  segment: string;
  balance: number;
  insured_share: number;
  rate_beta: number;
  runoff_slow: number;
  runoff_fast: number;
  rate: number;
}

export interface WholesaleFunding {
  id: string;
  amount: number;
  maturity_days: number;
  rate: number;
}

export interface SwapHedge {
  id: string;
  notional: number;
  fixed_rate: number;
  maturity_years: number;
  pay_fixed: boolean;
}

export interface BankBalanceSheet {
  kind: "balance_sheet";
  name: string;
  as_of: string;
  currency: string;
  synthetic: boolean;
  assets: BsAsset[];
  loan_pools: LoanPool[];
  deposits: DepositSegment[];
  wholesale_funding: WholesaleFunding[];
  hedges: SwapHedge[];
  cet1_capital: number;
  risk_weighted_assets: number;
  policy_rate: number;
  governance: Record<string, number | string | boolean>;
}

export interface ClimateHolding {
  issuer: string;
  sector: string;
  market_value: number;
  evic: number;
  revenue: number;
  ebitda: number | null;
  scope1: number | null;
  scope2: number | null;
  scope3: number | null;
  data_quality: number | null;
  emissions_year: number | null;
  controversy_flags: string[];
  exclusion_flags: string[];
}

export interface ClimatePortfolio {
  kind: "climate";
  name: string;
  as_of: string;
  currency: string;
  synthetic: boolean;
  holdings: ClimateHolding[];
}

export type Dataset = MarketDataset | BankBalanceSheet | ClimatePortfolio;

// ------------------------------------------------------------------------------------------------
// Catalogue
// ------------------------------------------------------------------------------------------------

export interface ParamSpec {
  name: string;
  type: "float" | "int" | "str" | "bool";
  default: ParamValue;
  choices: ParamValue[] | null;
  minimum: number | null;
  maximum: number | null;
  /** Only meaningful when every listed parameter takes one of the listed values. */
  applies_when: Record<string, ParamValue[]> | null;
  description: string;
}

export interface MetricSpec {
  key: string;
  unit: Unit;
  description: string;
  higher_is_worse: boolean | null;
  optional: boolean;
}

export interface ModelSpec {
  model_id: string;
  question: QuestionId;
  dataset_kind: DatasetKind;
  title: string;
  description: string;
  params: ParamSpec[];
  metrics: MetricSpec[];
  labels: Record<string, string[]>;
  method_param: string | null;
  pass_label: string | null;
}

export interface Metric {
  value: number;
  unit: Unit;
  trace_id: string | null;
  trace_step: string | null;
}

export interface ModelOutput {
  model_id: string;
  params: Record<string, ParamValue>;
  metrics: Record<string, Metric>;
  labels: Record<string, string>;
  traces: Trace[];
  findings: DataQualityFinding[];
  warnings: string[];
}

// ------------------------------------------------------------------------------------------------
// Plans, variations, comparison
// ------------------------------------------------------------------------------------------------

export interface GridSpec {
  model_id: string;
  dimensions: Record<string, ParamValue[]>;
  fixed: Record<string, ParamValue>;
}

export interface ExtraRun {
  model_id: string;
  params: Record<string, ParamValue>;
}

export interface QuestionPlan {
  question: QuestionId;
  grid: GridSpec;
  extras: ExtraRun[];
  max_variations: number;
}

export interface VariationSpec {
  variation_id: string;
  question: QuestionId;
  model_id: string;
  params: Record<string, ParamValue>;
  seed: number;
  role: "grid" | "extra";
}

export interface VariationResult {
  spec: VariationSpec;
  output: ModelOutput | null;
  error: string | null;
  duration_ms: number;
}

export interface MetricRange {
  unit: Unit;
  min: number;
  median: number;
  max: number;
  n: number;
}

export interface SensitivityRow {
  dimension: string;
  metric: string;
  /** Dimension value (as string) -> median of the metric. */
  medians: Record<string, number>;
  effect: number;
}

export interface ConclusionFlip {
  label: string;
  dimension: string;
  from_value: string;
  to_value: string;
  outcome_from: string;
  outcome_to: string;
  description: string;
}

export interface BreakEven {
  name: string;
  value: number | null;
  unit: Unit;
  found: boolean;
  trace_id: string | null;
  description: string;
}

export interface Comparison {
  question: QuestionId;
  metric_ranges: Record<string, MetricRange>;
  method_spread: Record<string, number>;
  sensitivity: SensitivityRow[];
  flips: ConclusionFlip[];
  break_evens: BreakEven[];
  label_counts: Record<string, Record<string, number>>;
}

// ------------------------------------------------------------------------------------------------
// Qualitative assessment (judgment)
// ------------------------------------------------------------------------------------------------

export interface Evidence {
  kind: EvidenceKind;
  ref: string;
  description: string;
}

export interface QualitativeFactor {
  factor_id: string;
  name: string;
  description: string;
  likelihood: number;
  impact: number;
  control: ControlStrength;
  inherent: Rating;
  residual: Rating;
  evidence: Evidence[];
  rationale: string;
  source: FactorSource;
}

export interface Override {
  factor_id: string;
  field: string;
  old: Json;
  new: Json;
  reason: string;
  by: string;
  at: string;
}

export interface QualitativeAssessment {
  question: QuestionId;
  label: "judgment";
  factors: QualitativeFactor[];
  overall: Rating;
  overrides: Override[];
  method_note: string;
}

// ------------------------------------------------------------------------------------------------
// Runs, review, reports
// ------------------------------------------------------------------------------------------------

export interface RunRequest {
  question: QuestionId;
  dataset: Dataset;
  plan?: QuestionPlan | null;
  seed?: number;
  use_llm?: boolean;
}

export interface RunRecord {
  run_id: string;
  question: QuestionId;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  input_hash: string;
  contract_version: string;
  n_variations: number;
  dataset_name: string;
  synthetic: boolean;
  error: string | null;
}

export interface VerifierFinding {
  location: string;
  text: string;
  value: number | null;
  matched: boolean;
  message: string;
}

export interface RunResult {
  run: RunRecord;
  plan: QuestionPlan;
  variations: VariationResult[];
  comparison: Comparison;
  assessment: QualitativeAssessment;
  verifier_findings: VerifierFinding[];
}

export interface FactorEdit {
  factor_id: string;
  likelihood?: number | null;
  impact?: number | null;
  control?: ControlStrength | null;
  rationale?: string | null;
  /** Mandatory: why the analyst changed the rating. */
  reason: string;
}

export interface ReviewSubmission {
  decision: ReviewDecision;
  reviewer: string;
  comment?: string;
  factor_edits?: FactorEdit[];
}

export interface SignOff {
  reviewer: string;
  decision: ReviewDecision;
  comment: string;
  at: string;
}

export interface AuditEvent {
  run_id: string;
  at: string;
  actor: string;
  event: string;
  detail: Record<string, Json>;
}

export interface Report {
  run: RunRecord;
  headline: string[];
  comparison: Comparison;
  assessment: QualitativeAssessment;
  signoff: SignOff | null;
  markdown: string;
}

export interface CalcRequest {
  model_id: string;
  dataset: Dataset;
  params?: Record<string, ParamValue>;
  seed?: number;
}

export interface QuestionInfo {
  question: QuestionId;
  title: string;
  description: string;
  dataset_kind: DatasetKind;
  default_plan: QuestionPlan;
}

export interface ErrorBody {
  code: ErrorCode;
  message: string;
  details: Record<string, Json>;
}

export interface Health {
  status: string;
  contract_version: string;
}
