namespace Riskbot.App.Bus.Events;

public sealed class EnrichmentStartedEvent : IRiskEvent
{
    public required string PortfolioName { get; init; }
    public required long EnrichGeneration { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
