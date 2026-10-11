namespace Riskbot.App.Bus.Events;

/// <summary>Current limit breaches after enrichment or VaR refresh.</summary>
public sealed class RiskBreachesUpdatedEvent : IRiskEvent
{
    public required long EnrichGeneration { get; init; }

    /// <summary>Ticker → breach reason codes (e.g. concentration, exclusion, esg).</summary>
    public required IReadOnlyDictionary<string, IReadOnlyList<string>> PositionBreaches { get; init; }

    /// <summary>Portfolio-wide breaches (e.g. var_limit, portfolio_esg).</summary>
    public required IReadOnlyList<string> PortfolioBreaches { get; init; }

    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
