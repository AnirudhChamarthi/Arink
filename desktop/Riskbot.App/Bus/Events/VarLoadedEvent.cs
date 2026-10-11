namespace Riskbot.App.Bus.Events;

public sealed class VarLoadedEvent : IRiskEvent
{
    public required string PortfolioSessionId { get; init; }
    public required long EnrichGeneration { get; init; }
    public required IReadOnlyDictionary<string, double> ContributionPctByTicker { get; init; }

    /// <summary>Portfolio VaR as a decimal (e.g. 0.0473 = 4.73%).</summary>
    public required double PortfolioVar { get; init; }

    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
