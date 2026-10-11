using Riskbot.App.ApiClient;

namespace Riskbot.App.Bus.Events;

public sealed class NlqResultEvent : IRiskEvent
{
    public required NlqResultDto Result { get; init; }
    public required long EnrichGeneration { get; init; }
    public required string Query { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
