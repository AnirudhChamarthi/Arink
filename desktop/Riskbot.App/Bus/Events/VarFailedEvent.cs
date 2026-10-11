namespace Riskbot.App.Bus.Events;

public sealed class VarFailedEvent : IRiskEvent
{
    public required string PortfolioSessionId { get; init; }
    public required long EnrichGeneration { get; init; }
    public required string Message { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
