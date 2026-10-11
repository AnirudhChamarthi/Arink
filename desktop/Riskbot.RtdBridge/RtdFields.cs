namespace Riskbot.RtdBridge;

/// <summary>RTD topic field names — second argument in =RTD("Riskbot.RTD",,"TICKER","Field").</summary>
public static class RtdFields
{
    public const string CurrentPrice = "CurrentPrice";
    public const string MarketValue = "MarketValue";
    public const string PnL = "PnL";
    public const string PnLPct = "PnLPct";
    public const string WeightPct = "WeightPct";
    public const string Beta = "Beta";
    public const string Delta = "Delta";
    public const string EsgScore = "EsgScore";
    public const string CarbonIntensity = "CarbonIntensity";
    public const string VarContributionPct = "VarContributionPct";

    public static readonly string[] All =
    {
        CurrentPrice,
        MarketValue,
        PnL,
        PnLPct,
        WeightPct,
        Beta,
        Delta,
        EsgScore,
        CarbonIntensity,
        VarContributionPct,
    };
}
