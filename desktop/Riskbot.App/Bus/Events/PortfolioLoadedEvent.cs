using Riskbot.App.Models;

namespace Riskbot.App.Bus.Events;

public sealed class PortfolioLoadedEvent : IRiskEvent
{
    public required PortfolioFile Portfolio { get; init; }
    public DateTimeOffset OccurredAt { get; init; } = DateTimeOffset.UtcNow;
}
