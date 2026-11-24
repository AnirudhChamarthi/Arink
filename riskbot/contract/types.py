"""Data transfer objects shared by every component.

Rules
-----
* These are plain data: no behaviour beyond validation.
* Every model forbids unknown fields, so drift between components fails loudly.
* Numbers that leave a model carry a ``Unit`` and, where they come from a calculation, the id of the
  ``Trace`` (and step) that produced them.
* Changing anything here is a contract change: bump ``CONTRACT_VERSION`` in ``__init__.py`` and record
  it in CONTRACT.md.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------------------------


class QuestionId(str, Enum):
    Q1 = "q1_market"  # How much could we lose in a bad week, and how far should we trust that number?
    Q2 = "q2_balance_sheet"  # Could a bank-like balance sheet survive a rate shock plus a deposit run?
    Q3 = "q3_transition"  # How exposed is this portfolio to the low-carbon transition, and how good is the data?


class DatasetKind(str, Enum):
    MARKET = "market"
    BALANCE_SHEET = "balance_sheet"
    CLIMATE = "climate"


class Unit(str, Enum):
    FRACTION_OF_GROSS = "fraction_of_gross"  # loss as a fraction of gross exposure
    FRACTION = "fraction"  # any other ratio expressed as a fraction (0.07 = 7%)
    CURRENCY = "currency"  # in the dataset's currency
    BASIS_POINTS = "bp"
    COUNT = "count"
    RATIO = "ratio"  # unitless ratio that is not naturally a percentage (e.g. LCR 1.2)
    PROBABILITY = "probability"  # p-values and probabilities
    TCO2E = "tCO2e"
    TCO2E_PER_MUSD = "tCO2e_per_musd"
    DAYS = "days"
    YEARS = "years"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# --------------------------------------------------------------------------------------------
# Traces: the step-by-step working behind every number
# --------------------------------------------------------------------------------------------

TableCell = Union[float, int, str, bool, None]


class TraceStep(_Model):
    id: str = Field(description="Stable id unique within the trace, e.g. 'portfolio_variance'.")
    title: str
    formula: str = Field(description="LaTeX without surrounding $ delimiters.")
    substitution: str = Field(description="The formula with numbers filled in, plain text or LaTeX.")
    value: float | None = None
    unit: Unit | None = None
    table: list[dict[str, TableCell]] | None = Field(default=None, description="Per-row detail for vector steps.")
    note: str = ""


class Trace(_Model):
    trace_id: str = Field(description="'<model_id>-<first 12 hex of input_hash>'; deterministic.")
    model_id: str
    title: str
    assumptions: list[str]
    inputs: dict[str, Any] = Field(description="Small summary of inputs (parameters, counts), not raw data.")
    steps: list[TraceStep]
    result: dict[str, float] = Field(description="Final named values; each must equal a metric of the output.")
    input_hash: str = Field(description="SHA-256 hex of the canonical JSON of (model_id, dataset, params, seed).")
    warnings: list[str] = []


# --------------------------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------------------------


class DataQualityFinding(_Model):
    check: str = Field(description="Short machine id, e.g. 'missing_returns', 'stale_price'.")
    severity: Severity
    field: str
    subject: str | None = Field(default=None, description="Ticker, issuer, segment... if specific.")
    count: int = 0
    message: str


# --------------------------------------------------------------------------------------------
# Datasets (inputs). A Dataset is a discriminated union on `kind`.
# --------------------------------------------------------------------------------------------


class MarketPosition(_Model):
    ticker: str
    asset_class: Literal["equity", "fixed_income", "commodity", "cash", "other"] = "equity"
    sector: str | None = None
    quantity: float = Field(description="Signed: negative is short.")
    price: float = Field(gt=0)
    currency: str = "USD"


class MarketDataset(_Model):
    kind: Literal["market"] = "market"
    name: str
    base_currency: str = "USD"
    as_of: dt.date
    synthetic: bool = Field(description="True if generated; shown as a banner in every UI.")
    positions: list[MarketPosition] = Field(min_length=1)
    dates: list[dt.date] = Field(description="Ascending trading dates of the return history.")
    returns: dict[str, list[float | None]] = Field(
        description="Daily simple returns per ticker, aligned with `dates`; None marks a missing value."
    )

    @model_validator(mode="after")
    def _aligned(self) -> MarketDataset:
        n = len(self.dates)
        if any(b <= a for a, b in zip(self.dates, self.dates[1:])):
            raise ValueError("dates must be strictly ascending")
        for t, series in self.returns.items():
            if len(series) != n:
                raise ValueError(f"returns[{t!r}] has {len(series)} values for {n} dates")
        missing = {p.ticker for p in self.positions if p.asset_class != "cash"} - set(self.returns)
        if missing:
            raise ValueError(f"no return history for non-cash positions: {sorted(missing)}")
        return self


class BsAsset(_Model):
    id: str
    kind: Literal["cash", "hqla_securities", "afs_securities", "htm_securities", "loans", "other"]
    book_value: float = Field(ge=0)
    market_value: float = Field(ge=0)
    coupon_rate: float = Field(description="Annual, as a fraction.")
    maturity_years: float = Field(ge=0)
    repricing_years: float = Field(ge=0, description="Time to next rate reset; equals maturity for fixed rate.")
    modified_duration: float | None = Field(default=None, description="If None, derived from coupon and maturity.")
    convexity: float | None = None
    hqla_level: Literal["1", "2a", "2b"] | None = None


class LoanPool(_Model):
    segment: str
    ead: float = Field(ge=0, description="Exposure at default (currency).")
    pd: float = Field(gt=0, lt=1, description="Through-the-cycle 1-year probability of default.")
    lgd: float = Field(ge=0, le=1)
    asset_correlation: float = Field(gt=0, lt=1, description="Vasicek rho.")


class DepositSegment(_Model):
    segment: str
    balance: float = Field(ge=0)
    insured_share: float = Field(ge=0, le=1)
    rate_beta: float = Field(ge=0, le=1, description="Share of a policy-rate change passed to depositors.")
    runoff_slow: float = Field(ge=0, le=1, description="30-day outflow fraction in a slow run.")
    runoff_fast: float = Field(ge=0, le=1, description="30-day outflow fraction in a fast run.")
    rate: float = Field(default=0.0, description="Current deposit rate (annual fraction).")


class WholesaleFunding(_Model):
    id: str
    amount: float = Field(ge=0)
    maturity_days: int = Field(ge=0)
    rate: float


class SwapHedge(_Model):
    id: str
    notional: float = Field(ge=0)
    fixed_rate: float
    maturity_years: float = Field(gt=0)
    pay_fixed: bool = True


class BankBalanceSheet(_Model):
    kind: Literal["balance_sheet"] = "balance_sheet"
    name: str
    as_of: dt.date
    currency: str = "USD"
    synthetic: bool
    assets: list[BsAsset] = Field(min_length=1)
    loan_pools: list[LoanPool] = Field(description="Credit view of the loan book; EAD should reconcile to loans.")
    deposits: list[DepositSegment]
    wholesale_funding: list[WholesaleFunding] = []
    hedges: list[SwapHedge] = []
    cet1_capital: float = Field(gt=0)
    risk_weighted_assets: float = Field(gt=0)
    policy_rate: float = Field(description="Current short rate (annual fraction).")
    governance: dict[str, float | int | str | bool] = Field(
        default_factory=dict,
        description="Qualitative evidence, e.g. {'cro_vacancy_months': 8, 'hedges_reduced_last_year': True}.",
    )


class ClimateHolding(_Model):
    issuer: str
    sector: str
    market_value: float = Field(description="Signed; shorts excluded from financed emissions.")
    evic: float = Field(gt=0, description="Enterprise value including cash.")
    revenue: float = Field(gt=0)
    ebitda: float | None = None
    scope1: float | None = Field(default=None, ge=0, description="tCO2e per year; None if not available.")
    scope2: float | None = Field(default=None, ge=0)
    scope3: float | None = Field(default=None, ge=0)
    data_quality: int | None = Field(default=None, ge=1, le=5, description="1 reported+verified ... 5 sector estimate.")
    emissions_year: int | None = None
    controversy_flags: list[str] = []
    exclusion_flags: list[str] = []


class ClimatePortfolio(_Model):
    kind: Literal["climate"] = "climate"
    name: str
    as_of: dt.date
    currency: str = "USD"
    synthetic: bool
    holdings: list[ClimateHolding] = Field(min_length=1)


Dataset = Annotated[Union[MarketDataset, BankBalanceSheet, ClimatePortfolio], Field(discriminator="kind")]


# --------------------------------------------------------------------------------------------
# Model catalogue types
# --------------------------------------------------------------------------------------------


class ParamSpec(_Model):
    name: str
    type: Literal["float", "int", "str", "bool"]
    default: Any = None
    choices: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    applies_when: dict[str, list[Any]] | None = Field(
        default=None,
        description="Parameter is only meaningful when every listed parameter takes one of the listed values; "
        "otherwise the planner drops it (prevents duplicate variations).",
    )
    description: str


class MetricSpec(_Model):
    key: str
    unit: Unit
    description: str
    higher_is_worse: bool | None = None
    optional: bool = Field(default=False, description="May be absent (e.g. only when a parameter is set).")


class ModelSpec(_Model):
    model_id: str = Field(description="'<question prefix>.<name>', e.g. 'q1.var'.")
    question: QuestionId
    dataset_kind: DatasetKind
    title: str
    description: str
    params: list[ParamSpec]
    metrics: list[MetricSpec]
    labels: dict[str, list[str]] = Field(default_factory=dict, description="Categorical outputs and allowed values.")
    method_param: str | None = Field(default=None, description="Parameter whose spread measures model risk.")
    pass_label: str | None = Field(default=None, description="Label whose values are 'pass'/'fail'.")


class Metric(_Model):
    value: float
    unit: Unit
    trace_id: str | None = None
    trace_step: str | None = None


class ModelOutput(_Model):
    model_id: str
    params: dict[str, Any] = Field(description="Effective parameters after defaults were applied.")
    metrics: dict[str, Metric]
    labels: dict[str, str] = {}
    traces: list[Trace]
    findings: list[DataQualityFinding] = []
    warnings: list[str] = []


# --------------------------------------------------------------------------------------------
# Plans, variations and comparison
# --------------------------------------------------------------------------------------------


class GridSpec(_Model):
    model_id: str
    dimensions: dict[str, list[Any]] = Field(description="Parameter name -> values to vary (cartesian product).")
    fixed: dict[str, Any] = {}


class ExtraRun(_Model):
    model_id: str
    params: dict[str, Any] = {}


class QuestionPlan(_Model):
    question: QuestionId
    grid: GridSpec
    extras: list[ExtraRun] = Field(default_factory=list, description="Models run once each (data quality, reverse stress).")
    max_variations: int = Field(default=200, ge=1, le=1000)


class VariationSpec(_Model):
    variation_id: str = Field(description="Deterministic: 'v' + 10 hex of hash(model_id, params).")
    question: QuestionId
    model_id: str
    params: dict[str, Any]
    seed: int
    role: Literal["grid", "extra"] = "grid"


class VariationResult(_Model):
    spec: VariationSpec
    output: ModelOutput | None = None
    error: str | None = None
    duration_ms: float


class MetricRange(_Model):
    unit: Unit
    min: float
    median: float
    max: float
    n: int


class SensitivityRow(_Model):
    dimension: str
    metric: str
    medians: dict[str, float] = Field(description="Dimension value (as string) -> median of the metric.")
    effect: float = Field(description="max(medians) - min(medians).")


class ConclusionFlip(_Model):
    label: str
    dimension: str
    from_value: str
    to_value: str
    outcome_from: str
    outcome_to: str
    description: str


class BreakEven(_Model):
    name: str = Field(description="Metric key from an extra run, starting with 'breakeven_'.")
    value: float | None
    unit: Unit
    found: bool
    trace_id: str | None = None
    description: str


class Comparison(_Model):
    question: QuestionId
    metric_ranges: dict[str, MetricRange]
    method_spread: dict[str, float] = Field(default_factory=dict, description="Metric -> max/min across methods.")
    sensitivity: list[SensitivityRow] = []
    flips: list[ConclusionFlip] = []
    break_evens: list[BreakEven] = []
    label_counts: dict[str, dict[str, int]] = Field(default_factory=dict, description="Label -> value -> count.")


# --------------------------------------------------------------------------------------------
# Qualitative assessment (judgment, clearly labelled)
# --------------------------------------------------------------------------------------------


class Rating(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ControlStrength(str, Enum):
    WEAK = "weak"
    ADEQUATE = "adequate"
    STRONG = "strong"


class FactorSource(str, Enum):
    RULE = "rule"
    LLM_DRAFT = "llm_draft"
    ANALYST = "analyst"
    UNASSESSED = "unassessed"


class Evidence(_Model):
    kind: Literal["trace", "finding", "metric", "dataset_field", "note"]
    ref: str = Field(description="trace_id[/step], finding check, metric key, dataset field path, or free text.")
    description: str


class QualitativeFactor(_Model):
    factor_id: str
    name: str
    description: str
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    control: ControlStrength
    inherent: Rating
    residual: Rating
    evidence: list[Evidence] = []
    rationale: str
    source: FactorSource


class Override(_Model):
    factor_id: str
    field: str
    old: Any
    new: Any
    reason: str
    by: str
    at: dt.datetime


class QualitativeAssessment(_Model):
    question: QuestionId
    label: Literal["judgment"] = "judgment"
    factors: list[QualitativeFactor]
    overall: Rating
    overrides: list[Override] = []
    method_note: str = Field(description="How ratings were derived; shown with the assessment.")


# --------------------------------------------------------------------------------------------
# Runs, review and reports
# --------------------------------------------------------------------------------------------


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class RunRequest(_Model):
    question: QuestionId
    dataset: Dataset
    plan: QuestionPlan | None = Field(default=None, description="None: use the question's default plan.")
    seed: int = 20261123
    use_llm: bool = Field(default=False, description="Allow an LLM to draft rubric rationales (verified).")


class RunRecord(_Model):
    run_id: str
    question: QuestionId
    status: RunStatus
    created_at: dt.datetime
    updated_at: dt.datetime
    input_hash: str
    contract_version: str
    n_variations: int
    dataset_name: str
    synthetic: bool
    error: str | None = None


class VerifierFinding(_Model):
    location: str = Field(description="Where the number was found, e.g. 'factor:uninsured_share/rationale'.")
    text: str
    value: float | None
    matched: bool
    message: str


class RunResult(_Model):
    run: RunRecord
    plan: QuestionPlan
    variations: list[VariationResult]
    comparison: Comparison
    assessment: QualitativeAssessment
    verifier_findings: list[VerifierFinding] = []


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class FactorEdit(_Model):
    factor_id: str
    likelihood: int | None = Field(default=None, ge=1, le=5)
    impact: int | None = Field(default=None, ge=1, le=5)
    control: ControlStrength | None = None
    rationale: str | None = None
    reason: str = Field(min_length=1)


class ReviewSubmission(_Model):
    decision: ReviewDecision
    reviewer: str = Field(min_length=1)
    comment: str = ""
    factor_edits: list[FactorEdit] = []


class SignOff(_Model):
    reviewer: str
    decision: ReviewDecision
    comment: str
    at: dt.datetime


class AuditEvent(_Model):
    run_id: str
    at: dt.datetime
    actor: str = Field(description="'system', 'llm' or a reviewer name.")
    event: str
    detail: dict[str, Any] = {}


class Report(_Model):
    run: RunRecord
    headline: list[str] = Field(description="Short sentences; every number in them is verified against traces.")
    comparison: Comparison
    assessment: QualitativeAssessment
    signoff: SignOff | None = None
    markdown: str


class CalcRequest(_Model):
    model_id: str
    dataset: Dataset
    params: dict[str, Any] = {}
    seed: int = 20261123


class QuestionInfo(_Model):
    question: QuestionId
    title: str
    description: str
    dataset_kind: DatasetKind
    default_plan: QuestionPlan


class ErrorBody(_Model):
    code: Literal["not_found", "validation_failed", "conflict", "limit_exceeded", "internal"]
    message: str
    details: dict[str, Any] = {}
