namespace Riskbot.App.Bus.Events;

public sealed class NlqCancelledEvent : IRiskEvent
{
    public required long EnrichGeneration { get; init; }
    public required string Query { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
