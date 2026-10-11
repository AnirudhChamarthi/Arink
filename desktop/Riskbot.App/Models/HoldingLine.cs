namespace Riskbot.App.Models;

public sealed class HoldingLine
{
    public DateOnly? Date { get; init; }
    public required string Ticker { get; init; }
    public string? Isin { get; init; }
    public required string AssetClass { get; init; }
    public double Quantity { get; init; }
    public double CostPrice { get; init; }
    public required string Currency { get; init; }
    public string? Sector { get; init; }
    public string? Country { get; init; }
    public double? EsgOverride { get; init; }
}
