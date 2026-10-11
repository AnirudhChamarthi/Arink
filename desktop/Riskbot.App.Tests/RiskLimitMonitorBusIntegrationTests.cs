using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

/// <summary>Step 10/11 — limit monitor publishes breach events on the message bus.</summary>
public class RiskLimitMonitorBusIntegrationTests
{
    [Fact]
    public async Task RefreshAsync_publishes_position_breach_for_concentration()
    {
        await using var bus = new MessageBus();
        var tcs = new TaskCompletionSource<RiskBreachesUpdatedEvent>();

        bus.Subscribe<RiskBreachesUpdatedEvent>(e =>
        {
            tcs.TrySetResult(e);
            return Task.CompletedTask;
        });

        var esg = new EsgPreferencesService(new EsgPreferencesStore());
        var workspace = new PortfolioWorkspaceService(
            new ExcelIntegration.PortfolioFileManager(new ExcelIntegration.PortfolioValidator()),
            new ExcelIntegration.TemplateWriter(),
            bus,
            new RecentFilesStore());

        var monitor = new RiskLimitMonitorService(bus, workspace, esg);
        monitor.ApplyLimits(new RiskLimitsDto { MaxConcentration = 0.10 });

        monitor.SyncRows(
        [
            new BlotterRow
            {
                Ticker = "BIG",
                WeightPercent = 25,
                MarketValue = 250,
                EsgScore = 70,
            },
            new BlotterRow
            {
                Ticker = "SMALL",
                WeightPercent = 5,
                MarketValue = 50,
                EsgScore = 70,
            },
        ]);

        await monitor.RefreshAsync(generation: 42);

        var evt = await tcs.Task.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Equal(42, evt.EnrichGeneration);
        Assert.True(evt.PositionBreaches.ContainsKey("BIG"));
        Assert.Contains(RiskLimitMonitor.Concentration, evt.PositionBreaches["BIG"]);
        Assert.False(evt.PositionBreaches.ContainsKey("SMALL"));
    }

    [Fact]
    public async Task Var_loaded_triggers_breach_when_over_limit()
    {
        await using var bus = new MessageBus();

        var esg = new EsgPreferencesService(new EsgPreferencesStore());
        var workspace = new PortfolioWorkspaceService(
            new ExcelIntegration.PortfolioFileManager(new ExcelIntegration.PortfolioValidator()),
            new ExcelIntegration.TemplateWriter(),
            bus,
            new RecentFilesStore());

        typeof(PortfolioWorkspaceService)
            .GetProperty(nameof(PortfolioWorkspaceService.Current))!
            .SetValue(workspace, new PortfolioFile
            {
                FilePath = "C:\\test.xlsx",
                Metadata = new PortfolioMetadata
                {
                    PortfolioName = "Test",
                    BaseCurrency = "USD",
                    VarLimit = 0.04,
                },
                Holdings = [],
            });

        var monitor = new RiskLimitMonitorService(bus, workspace, esg);
        monitor.SyncRows([new BlotterRow { Ticker = "AAPL", WeightPercent = 100, MarketValue = 100, EsgScore = 80 }]);

        var tcs = new TaskCompletionSource<RiskBreachesUpdatedEvent>();
        bus.Subscribe<RiskBreachesUpdatedEvent>(e =>
        {
            if (e.PortfolioBreaches.Contains(RiskLimitMonitor.VarLimit))
                tcs.TrySetResult(e);
            return Task.CompletedTask;
        });

        await bus.PublishAsync(new EnrichmentStartedEvent
        {
            EnrichGeneration = 7,
            PortfolioName = "Test",
        });

        await bus.PublishAsync(new VarLoadedEvent
        {
            EnrichGeneration = 7,
            PortfolioSessionId = "sess",
            ContributionPctByTicker = new Dictionary<string, double> { ["AAPL"] = 100 },
            PortfolioVar = 0.06,
        });

        var evt = await tcs.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.Contains(RiskLimitMonitor.VarLimit, evt.PortfolioBreaches);
    }
}
