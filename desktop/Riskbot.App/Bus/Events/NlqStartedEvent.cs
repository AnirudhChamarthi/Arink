namespace Riskbot.App.Bus.Events;

public sealed class NlqStartedEvent : IRiskEvent
{
    public required string Query { get; init; }
    public required long EnrichGeneration { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
