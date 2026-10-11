using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;

namespace Riskbot.App.Tests;

public class MessageBusTests
{
    [Fact]
    public async Task Publish_delivers_event_to_subscriber()
    {
        await using var bus = new MessageBus();
        var tcs = new TaskCompletionSource<PortfolioLoadedEvent>();

        bus.Subscribe<PortfolioLoadedEvent>(e =>
        {
            tcs.TrySetResult(e);
            return Task.CompletedTask;
        });

        var evt = new PortfolioLoadedEvent
        {
            Portfolio = new Models.PortfolioFile
            {
                FilePath = "C:\\test.xlsx",
                Metadata = new Models.PortfolioMetadata
                {
                    PortfolioName = "BusTest",
                    BaseCurrency = "USD",
                },
                Holdings = [],
            },
        };

        await bus.PublishAsync(evt);
        var received = await tcs.Task.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Equal("BusTest", received.Portfolio.Metadata.PortfolioName);
    }

    [Fact]
    public async Task Subscriber_does_not_receive_other_event_types()
    {
        await using var bus = new MessageBus();
        var hit = 0;

        bus.Subscribe<PortfolioLoadedEvent>(_ =>
        {
            Interlocked.Increment(ref hit);
            return Task.CompletedTask;
        });

        await bus.PublishAsync(new VarLoadedEvent
        {
            PortfolioSessionId = "s",
            EnrichGeneration = 1,
            ContributionPctByTicker = new Dictionary<string, double>(),
            PortfolioVar = 0.03,
        });

        await Task.Delay(100);
        Assert.Equal(0, hit);
    }
}
