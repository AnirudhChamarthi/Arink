namespace Riskbot.App.Bus.Events;

public sealed class NlqFailedEvent : IRiskEvent
{
    public required long EnrichGeneration { get; init; }
    public required string Query { get; init; }
    public required string Message { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
