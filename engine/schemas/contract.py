"""Pydantic models aligned with shared/openapi.yaml."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AssetClass(str, Enum):
    EQUITY = "Equity"
    FIXED_INCOME = "FixedIncome"
    COMMODITY = "Commodity"
    CASH = "Cash"


class RawPosition(BaseModel):
    ticker: str
    isin: str | None = None
    asset_class: AssetClass
    quantity: float
    cost_price: float
    currency: str
    sector: str | None = None
    country: str | None = None
    esg_override: float | None = None


class OptionsStrike(BaseModel):
    strike: float
    expiry: date
    call_bid: float
    call_ask: float
    put_bid: float
    put_ask: float
    call_iv: float
    put_iv: float
    open_interest: int | None = None


class OptionsChain(BaseModel):
    ticker: str
    strikes: list[OptionsStrike]


class EnrichedPosition(RawPosition):
    name: str = ""
    current_price: float
    returns_252d: list[float]
    implied_vol: float
    risk_free_rate: float
    esg_score: float
    carbon_intensity: float
    market_cap: float | None = None
    beta: float | None = None
    has_options: bool = False
    options_chain: OptionsChain | None = None


class EnrichedPortfolio(BaseModel):
    portfolio_name: str
    base_currency: str
    benchmark: str | None = None
    positions: list[EnrichedPosition]


class EnrichedPositionDisplay(RawPosition):
    """Blotter / UI fields only — no return series or options chain."""

    name: str = ""
    current_price: float
    implied_vol: float
    risk_free_rate: float
    esg_score: float
    carbon_intensity: float
    market_cap: float | None = None
    beta: float | None = None
    has_options: bool = False


class EnrichedPortfolioDisplay(BaseModel):
    portfolio_name: str
    base_currency: str
    benchmark: str | None = None
    positions: list[EnrichedPositionDisplay]


class ResponseDetail(str, Enum):
    DISPLAY = "display"
    FULL = "full"


class EnrichResponse(BaseModel):
    portfolio_session_id: str
    response_detail: ResponseDetail
    portfolio: EnrichedPortfolio | EnrichedPortfolioDisplay


class EnrichRequest(BaseModel):
    portfolio_name: str
    base_currency: str
    benchmark: str | None = None
    positions: list[RawPosition]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = "1.0.0"


class VarMethod(str, Enum):
    PARAMETRIC = "parametric"
    HISTORICAL = "historical"
    MONTECARLO = "montecarlo"


class VarContribution(BaseModel):
    ticker: str
    var_contribution: float
    pct_of_total: float


class VarResult(BaseModel):
    var: float
    cvar: float
    method: VarMethod
    confidence: float
    horizon_days: int
    contributions: list[VarContribution]
    confidence_interval_low: float | None = None
    confidence_interval_high: float | None = None


class VarRequest(BaseModel):
    portfolio_session_id: str | None = None
    portfolio: EnrichedPortfolio | None = None
    method: VarMethod
    confidence: float = Field(ge=0.5, le=0.999)
    horizon_days: int = Field(ge=1, le=252)
    n_sims: int = Field(default=10000, ge=100)

    @model_validator(mode="after")
    def require_portfolio_source(self) -> "VarRequest":
        if not self.portfolio_session_id and self.portfolio is None:
            raise ValueError("Provide portfolio_session_id or portfolio.")
        return self


class RiskLimits(BaseModel):
    var_limit: float | None = None
    max_concentration: float | None = None
    esg_min_score: float | None = None
    exclusion_filters: list[str] = Field(default_factory=list)


class NlqRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    portfolio_session_id: str | None = None
    portfolio: EnrichedPortfolio | None = None
    limits: RiskLimits = Field(default_factory=RiskLimits)

    @model_validator(mode="after")
    def require_portfolio_source(self) -> "NlqRequest":
        if not self.portfolio_session_id and self.portfolio is None:
            raise ValueError("Provide portfolio_session_id or portfolio.")
        return self


class NlqResult(BaseModel):
    topline_number: str
    topline_label: str
    formula_breakdown: list[str]
    explanation: str
    excel_report_path: str
    models_used: list[str]


class GreeksMethod(str, Enum):
    BLACK_SCHOLES = "black_scholes"
    SYNTHETIC_FINITE_DIFFERENCE = "synthetic_finite_difference"


class PositionGreeks(BaseModel):
    ticker: str
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    greeks_method: GreeksMethod


class PortfolioGreeks(BaseModel):
    positions: list[PositionGreeks]
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_vega: float
    portfolio_theta: float
    portfolio_rho: float


class StressScenario(str, Enum):
    CREDIT_2008 = "2008_credit"
    COVID_2020 = "covid_2020"
    RATE_SHOCK_200BPS = "rate_shock_200bps"
    OIL_SPIKE_50PCT = "oil_spike_50pct"
    CUSTOM = "custom"


class StressPositionResult(BaseModel):
    ticker: str
    pnl_impact: float
    pct_impact: float


class StressResult(BaseModel):
    scenario: str
    portfolio_pnl: float
    portfolio_pct: float
    positions: list[StressPositionResult]
    worst_positions: list[StressPositionResult]
    excel_report_path: str = ""


class ExclusionBreach(BaseModel):
    ticker: str
    filter: str
    reason: str


class PositionEsgRow(BaseModel):
    ticker: str
    esg_score: float
    carbon_intensity: float
    weight: float


class SustainabilityResult(BaseModel):
    portfolio_esg_score: float
    carbon_intensity_weighted: float
    carbon_var: float
    paris_alignment_gap_pct: float
    exclusion_breaches: list[ExclusionBreach]
    stranded_asset_exposure_pct: float
    per_position_esg: list[PositionEsgRow] = Field(default_factory=list)


class ArmaOrder(BaseModel):
    p: int
    q: int


class GarchResult(BaseModel):
    ticker: str
    omega: float
    alpha: float
    beta_param: float
    log_likelihood: float
    aic: float
    bic: float
    vol_forecast_10d: float
    conditional_var_1d: float
    vol_forecast_series: list[float] = Field(default_factory=list)
    arma_order: ArmaOrder | None = None


class _PortfolioSourceMixin(BaseModel):
    portfolio_session_id: str | None = None
    portfolio: EnrichedPortfolio | None = None

    @model_validator(mode="after")
    def require_portfolio_source(self):
        if not self.portfolio_session_id and self.portfolio is None:
            raise ValueError("Provide portfolio_session_id or portfolio.")
        return self


class GreeksRequest(_PortfolioSourceMixin):
    pass


class StressRequest(_PortfolioSourceMixin):
    scenario: StressScenario
    custom_shocks: dict[str, float] | None = None


class SustainabilityRequest(_PortfolioSourceMixin):
    exclusion_filters: list[str] = Field(default_factory=list)
    include_carbon_var: bool = True
    carbon_price_shock: float = 50.0
    run_exclusion_check: bool = True


class GarchRequest(_PortfolioSourceMixin):
    ticker: str


class FullReportRequest(_PortfolioSourceMixin):
    method: VarMethod = VarMethod.PARAMETRIC
    confidence: float = Field(default=0.99, ge=0.5, le=0.999)
    horizon_days: int = Field(default=1, ge=1, le=252)
    stress_scenario: StressScenario = StressScenario.CREDIT_2008
    exclusion_filters: list[str] = Field(default_factory=list)


class FullReportResult(BaseModel):
    excel_report_path: str
    summary_text: str
    portfolio_name: str
