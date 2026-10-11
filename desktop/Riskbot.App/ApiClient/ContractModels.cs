using System.Text.Json.Serialization;

namespace Riskbot.App.ApiClient;

public sealed class HealthResponse
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("version")]
    public string Version { get; set; } = "";
}

public sealed class EnrichRequest
{
    [JsonPropertyName("portfolio_name")]
    public string PortfolioName { get; set; } = "";

    [JsonPropertyName("base_currency")]
    public string BaseCurrency { get; set; } = "";

    [JsonPropertyName("benchmark")]
    public string? Benchmark { get; set; }

    [JsonPropertyName("positions")]
    public List<RawPositionDto> Positions { get; set; } = [];
}

public sealed class RawPositionDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("isin")]
    public string? Isin { get; set; }

    [JsonPropertyName("asset_class")]
    public string AssetClass { get; set; } = "";

    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("cost_price")]
    public double CostPrice { get; set; }

    [JsonPropertyName("currency")]
    public string Currency { get; set; } = "";

    [JsonPropertyName("sector")]
    public string? Sector { get; set; }

    [JsonPropertyName("country")]
    public string? Country { get; set; }

    [JsonPropertyName("esg_override")]
    public double? EsgOverride { get; set; }
}

/// <summary>Slim enriched position for blotter — no returns_252d or options_chain.</summary>
public sealed class EnrichedPositionDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("isin")]
    public string? Isin { get; set; }

    [JsonPropertyName("asset_class")]
    public string AssetClass { get; set; } = "";

    [JsonPropertyName("quantity")]
    public double Quantity { get; set; }

    [JsonPropertyName("cost_price")]
    public double CostPrice { get; set; }

    [JsonPropertyName("currency")]
    public string Currency { get; set; } = "";

    [JsonPropertyName("sector")]
    public string? Sector { get; set; }

    [JsonPropertyName("country")]
    public string? Country { get; set; }

    [JsonPropertyName("esg_override")]
    public double? EsgOverride { get; set; }

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("current_price")]
    public double CurrentPrice { get; set; }

    [JsonPropertyName("implied_vol")]
    public double ImpliedVol { get; set; }

    [JsonPropertyName("risk_free_rate")]
    public double RiskFreeRate { get; set; }

    [JsonPropertyName("esg_score")]
    public double EsgScore { get; set; }

    [JsonPropertyName("carbon_intensity")]
    public double CarbonIntensity { get; set; }

    [JsonPropertyName("market_cap")]
    public double? MarketCap { get; set; }

    [JsonPropertyName("beta")]
    public double? Beta { get; set; }

    [JsonPropertyName("has_options")]
    public bool HasOptions { get; set; }
}

public sealed class EnrichedPortfolioDto
{
    [JsonPropertyName("portfolio_name")]
    public string PortfolioName { get; set; } = "";

    [JsonPropertyName("base_currency")]
    public string BaseCurrency { get; set; } = "";

    [JsonPropertyName("benchmark")]
    public string? Benchmark { get; set; }

    [JsonPropertyName("positions")]
    public List<EnrichedPositionDto> Positions { get; set; } = [];
}

public sealed class EnrichResponseDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string PortfolioSessionId { get; set; } = "";

    [JsonPropertyName("response_detail")]
    public string ResponseDetail { get; set; } = "display";

    [JsonPropertyName("portfolio")]
    public EnrichedPortfolioDto Portfolio { get; set; } = new();
}

public sealed class VarRequestDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }

    [JsonPropertyName("method")]
    public string Method { get; set; } = "parametric";

    [JsonPropertyName("confidence")]
    public double Confidence { get; set; } = 0.99;

    [JsonPropertyName("horizon_days")]
    public int HorizonDays { get; set; } = 1;
}

public sealed class VarContributionDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("var_contribution")]
    public double VarContribution { get; set; }

    [JsonPropertyName("pct_of_total")]
    public double PctOfTotal { get; set; }
}

public sealed class VarResultDto
{
    [JsonPropertyName("var")]
    public double Var { get; set; }

    [JsonPropertyName("cvar")]
    public double Cvar { get; set; }

    [JsonPropertyName("method")]
    public string Method { get; set; } = "";

    [JsonPropertyName("confidence")]
    public double Confidence { get; set; }

    [JsonPropertyName("horizon_days")]
    public int HorizonDays { get; set; }

    [JsonPropertyName("contributions")]
    public List<VarContributionDto> Contributions { get; set; } = [];
}

public sealed class RiskLimitsDto
{
    [JsonPropertyName("var_limit")]
    public double? VarLimit { get; set; }

    [JsonPropertyName("max_concentration")]
    public double? MaxConcentration { get; set; }

    [JsonPropertyName("esg_min_score")]
    public double? EsgMinScore { get; set; }

    [JsonPropertyName("exclusion_filters")]
    public List<string> ExclusionFilters { get; set; } = [];
}

public sealed class NlqRequestDto
{
    [JsonPropertyName("query")]
    public string Query { get; set; } = "";

    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }

    [JsonPropertyName("limits")]
    public RiskLimitsDto Limits { get; set; } = new();
}

public sealed class NlqResultDto
{
    [JsonPropertyName("topline_number")]
    public string ToplineNumber { get; set; } = "";

    [JsonPropertyName("topline_label")]
    public string ToplineLabel { get; set; } = "";

    [JsonPropertyName("formula_breakdown")]
    public List<string> FormulaBreakdown { get; set; } = [];

    [JsonPropertyName("explanation")]
    public string Explanation { get; set; } = "";

    [JsonPropertyName("excel_report_path")]
    public string ExcelReportPath { get; set; } = "";

    [JsonPropertyName("models_used")]
    public List<string> ModelsUsed { get; set; } = [];
}

public sealed class FullReportRequestDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }

    [JsonPropertyName("method")]
    public string Method { get; set; } = "parametric";

    [JsonPropertyName("confidence")]
    public double Confidence { get; set; } = 0.99;

    [JsonPropertyName("horizon_days")]
    public int HorizonDays { get; set; } = 1;

    [JsonPropertyName("stress_scenario")]
    public string StressScenario { get; set; } = "2008_credit";

    [JsonPropertyName("exclusion_filters")]
    public List<string> ExclusionFilters { get; set; } = [];
}

public sealed class FullReportResultDto
{
    [JsonPropertyName("excel_report_path")]
    public string ExcelReportPath { get; set; } = "";

    [JsonPropertyName("summary_text")]
    public string SummaryText { get; set; } = "";

    [JsonPropertyName("portfolio_name")]
    public string PortfolioName { get; set; } = "";
}

public sealed class PortfolioSessionRequestDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }
}

public sealed class PositionGreeksDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("delta")]
    public double Delta { get; set; }

    [JsonPropertyName("gamma")]
    public double Gamma { get; set; }

    [JsonPropertyName("vega")]
    public double Vega { get; set; }

    [JsonPropertyName("theta")]
    public double Theta { get; set; }

    [JsonPropertyName("rho")]
    public double Rho { get; set; }

    [JsonPropertyName("greeks_method")]
    public string GreeksMethod { get; set; } = "";
}

public sealed class PortfolioGreeksDto
{
    [JsonPropertyName("positions")]
    public List<PositionGreeksDto> Positions { get; set; } = [];

    [JsonPropertyName("portfolio_delta")]
    public double PortfolioDelta { get; set; }

    [JsonPropertyName("portfolio_gamma")]
    public double PortfolioGamma { get; set; }

    [JsonPropertyName("portfolio_vega")]
    public double PortfolioVega { get; set; }

    [JsonPropertyName("portfolio_theta")]
    public double PortfolioTheta { get; set; }

    [JsonPropertyName("portfolio_rho")]
    public double PortfolioRho { get; set; }
}

public sealed class StressPositionResultDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("pnl_impact")]
    public double PnlImpact { get; set; }

    [JsonPropertyName("pct_impact")]
    public double PctImpact { get; set; }
}

public sealed class StressResultDto
{
    [JsonPropertyName("scenario")]
    public string Scenario { get; set; } = "";

    [JsonPropertyName("portfolio_pnl")]
    public double PortfolioPnl { get; set; }

    [JsonPropertyName("portfolio_pct")]
    public double PortfolioPct { get; set; }

    [JsonPropertyName("positions")]
    public List<StressPositionResultDto> Positions { get; set; } = [];

    [JsonPropertyName("worst_positions")]
    public List<StressPositionResultDto> WorstPositions { get; set; } = [];

    [JsonPropertyName("excel_report_path")]
    public string ExcelReportPath { get; set; } = "";
}

public sealed class StressRequestDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }

    [JsonPropertyName("scenario")]
    public string Scenario { get; set; } = "";
}

public sealed class ExclusionBreachDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("filter")]
    public string Filter { get; set; } = "";

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";
}

public sealed class SustainabilityResultDto
{
    [JsonPropertyName("portfolio_esg_score")]
    public double PortfolioEsgScore { get; set; }

    [JsonPropertyName("carbon_intensity_weighted")]
    public double CarbonIntensityWeighted { get; set; }

    [JsonPropertyName("carbon_var")]
    public double CarbonVar { get; set; }

    [JsonPropertyName("paris_alignment_gap_pct")]
    public double ParisAlignmentGapPct { get; set; }

    [JsonPropertyName("exclusion_breaches")]
    public List<ExclusionBreachDto> ExclusionBreaches { get; set; } = [];

    [JsonPropertyName("stranded_asset_exposure_pct")]
    public double StrandedAssetExposurePct { get; set; }
}

public sealed class SustainabilityRequestDto
{
    [JsonPropertyName("portfolio_session_id")]
    public string? PortfolioSessionId { get; set; }

    [JsonPropertyName("exclusion_filters")]
    public List<string> ExclusionFilters { get; set; } = [];

    [JsonPropertyName("include_carbon_var")]
    public bool IncludeCarbonVar { get; set; } = true;

    [JsonPropertyName("carbon_price_shock")]
    public double CarbonPriceShock { get; set; } = 50.0;

    [JsonPropertyName("run_exclusion_check")]
    public bool RunExclusionCheck { get; set; } = true;
}

public sealed class GarchResultDto
{
    [JsonPropertyName("ticker")]
    public string Ticker { get; set; } = "";

    [JsonPropertyName("omega")]
    public double Omega { get; set; }

    [JsonPropertyName("alpha")]
    public double Alpha { get; set; }

    [JsonPropertyName("beta_param")]
    public double BetaParam { get; set; }

    [JsonPropertyName("vol_forecast_10d")]
    public double VolForecast10d { get; set; }

    [JsonPropertyName("conditional_var_1d")]
    public double ConditionalVar1d { get; set; }
}
