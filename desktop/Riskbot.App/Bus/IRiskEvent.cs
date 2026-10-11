namespace Riskbot.App.Bus;

public interface IRiskEvent
{
    DateTimeOffset OccurredAt { get; }
}
