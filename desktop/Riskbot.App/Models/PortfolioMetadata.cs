namespace Riskbot.App.Models;

public sealed class PortfolioMetadata
{
    public required string PortfolioName { get; init; }
    public required string BaseCurrency { get; init; }
    public string? Benchmark { get; init; }
    public double? VarLimit { get; init; }
    public double? MaxConcentration { get; init; }
    public double? EsgMinScore { get; init; }
    public string? ExclusionFilters { get; init; }
}
