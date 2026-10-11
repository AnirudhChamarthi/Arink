using Riskbot.App.ApiClient;

namespace Riskbot.App.Bus.Events;

public sealed class EnrichmentCompleteEvent : IRiskEvent
{
    public required EnrichedPositionDto Position { get; init; }
    public required long EnrichGeneration { get; init; }
    public int Index { get; init; }
    public int Total { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
