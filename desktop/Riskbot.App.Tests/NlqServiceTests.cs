using System.Net;
using System.Net.Http;
using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

/// <summary>NLQ service with mocked HTTP (no live engine).</summary>
public class NlqServiceTests
{
    [Fact]
    public async Task SubmitAsync_publishes_failed_event_when_api_errors()
    {
        await using var bus = new MessageBus();
        NlqFailedEvent? failed = null;
        bus.Subscribe<NlqFailedEvent>(e =>
        {
            failed = e;
            return Task.CompletedTask;
        });

        var handler = new StubHandler(_ => new HttpResponseMessage(HttpStatusCode.BadGateway));
        var client = new RiskbotApiClient(new HttpClient(handler) { BaseAddress = new Uri("http://test/") });

        var session = new PortfolioSessionState();
        var gen = session.BeginEnrich();
        session.SetEnrichResult(new EnrichResponseDto
        {
            PortfolioSessionId = "nlq-session",
            Portfolio = new EnrichedPortfolioDto(),
        });

        var busForWs = new MessageBus();
        var workspace = new PortfolioWorkspaceService(
            new ExcelIntegration.PortfolioFileManager(new ExcelIntegration.PortfolioValidator()),
            new ExcelIntegration.TemplateWriter(),
            busForWs,
            new RecentFilesStore());

        typeof(PortfolioWorkspaceService)
            .GetProperty(nameof(PortfolioWorkspaceService.Current))!
            .SetValue(workspace, new PortfolioFile
            {
                FilePath = "C:\\test.xlsx",
                Metadata = new PortfolioMetadata { PortfolioName = "NLQ", BaseCurrency = "USD" },
                Holdings = [],
            });

        var engine = new EngineHostService(client);
        typeof(EngineHostService)
            .GetMethod("SetState", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .Invoke(engine, [EngineConnectionState.Online, "online"]);

        await using var nlq = new NlqService(bus, client, session, workspace, engine, new EsgPreferencesService(new EsgPreferencesStore()));

        await nlq.SubmitAsync("What is my VaR?", gen);

        await Task.Delay(300);
        Assert.NotNull(failed);
        Assert.Equal("What is my VaR?", failed!.Query);
        Assert.False(string.IsNullOrWhiteSpace(failed.Message));

        await busForWs.DisposeAsync();
    }

    private sealed class StubHandler(Func<HttpRequestMessage, HttpResponseMessage> responder) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) =>
            Task.FromResult(responder(request));
    }
}
