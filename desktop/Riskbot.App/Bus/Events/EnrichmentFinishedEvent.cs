namespace Riskbot.App.Bus.Events;

public sealed class EnrichmentFinishedEvent : IRiskEvent
{
    public required string PortfolioSessionId { get; init; }
    public required long EnrichGeneration { get; init; }
    public required int PositionCount { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
