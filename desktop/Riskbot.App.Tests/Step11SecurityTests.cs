using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

/// <summary>Step 11 security — bus fault isolation, NLQ bounds, report path gate.</summary>
public class Step11SecurityTests
{
    [Fact]
    public async Task MessageBus_failing_subscriber_does_not_block_others()
    {
        await using var bus = new MessageBus();
        var tcs = new TaskCompletionSource<bool>();

        bus.Subscribe<PortfolioLoadedEvent>(_ => throw new InvalidOperationException("boom"));
        bus.Subscribe<PortfolioLoadedEvent>(_ =>
        {
            tcs.TrySetResult(true);
            return Task.CompletedTask;
        });

        await bus.PublishAsync(new PortfolioLoadedEvent
        {
            Portfolio = new PortfolioFile
            {
                FilePath = "C:\\test.xlsx",
                Metadata = new PortfolioMetadata { PortfolioName = "Sec", BaseCurrency = "USD" },
                Holdings = [],
            },
        });

        Assert.True(await tcs.Task.WaitAsync(TimeSpan.FromSeconds(2)));
    }

    [Fact]
    public async Task NlqService_rejects_query_over_max_length()
    {
        await using var bus = new MessageBus();
        var (nlq, gen) = CreateNlqHarness(bus, _ => new HttpResponseMessage(HttpStatusCode.OK));

        var longQuery = new string('x', NlqErrorSanitizer.MaxQueryLength + 1);
        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => nlq.SubmitAsync(longQuery, gen));
        Assert.Contains(NlqErrorSanitizer.MaxQueryLength.ToString(), ex.Message);
    }

    [Fact]
    public async Task NlqService_rejects_report_path_outside_reports_directory()
    {
        await using var bus = new MessageBus();
        NlqFailedEvent? failed = null;
        bus.Subscribe<NlqFailedEvent>(e =>
        {
            failed = e;
            return Task.CompletedTask;
        });

        var payload = JsonSerializer.Serialize(new
        {
            topline_number = "1%",
            topline_label = "VaR",
            formula_breakdown = Array.Empty<string>(),
            explanation = "x",
            models_used = new[] { "var:parametric" },
            excel_report_path = @"C:\Windows\Temp\evil.xlsx",
        });

        var (nlq, gen) = CreateNlqHarness(bus, _ => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(payload, Encoding.UTF8, "application/json"),
        });
        await nlq.SubmitAsync("What is VaR?", gen);
        await Task.Delay(300);

        Assert.NotNull(failed);
        Assert.Contains("invalid report path", failed!.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Report_path_validator_rejects_parent_segment()
    {
        var engineDir = Infrastructure.RepoPaths.FindEngineDirectory();
        if (engineDir is null)
            return;

        var reportsDir = Path.Combine(engineDir, "output", "reports");
        Directory.CreateDirectory(reportsDir);
        var outside = Path.Combine(Path.GetDirectoryName(reportsDir)!, "escape_step11.xlsx");
        File.WriteAllBytes(outside, []);
        try
        {
            var traversal = Path.Combine(reportsDir, "..", Path.GetFileName(outside));
            Assert.False(NlqReportPathValidator.TryValidate(traversal, out _));
        }
        finally
        {
            if (File.Exists(outside))
                File.Delete(outside);
        }
    }

    [Fact]
    public void Report_path_validator_rejects_non_xlsx_extension()
    {
        var engineDir = Infrastructure.RepoPaths.FindEngineDirectory();
        if (engineDir is null)
            return;

        var reportsDir = Path.Combine(engineDir, "output", "reports");
        Directory.CreateDirectory(reportsDir);
        var txt = Path.Combine(reportsDir, $"riskbot_txt_{Guid.NewGuid():N}.txt");
        File.WriteAllText(txt, "not excel");
        try
        {
            Assert.False(NlqReportPathValidator.TryValidate(txt, out _));
        }
        finally
        {
            File.Delete(txt);
        }
    }

    private static (NlqService Nlq, long Gen) CreateNlqHarness(
        MessageBus bus,
        Func<HttpRequestMessage, HttpResponseMessage> respond)
    {
        var handler = new StubHandler(respond);
        var client = new RiskbotApiClient(new HttpClient(handler) { BaseAddress = new Uri("http://test/") });
        var session = new PortfolioSessionState();
        var gen = session.BeginEnrich();
        session.SetEnrichResult(new EnrichResponseDto
        {
            PortfolioSessionId = "sec-session",
            Portfolio = new EnrichedPortfolioDto(),
        });

        var workspace = new PortfolioWorkspaceService(
            new ExcelIntegration.PortfolioFileManager(new ExcelIntegration.PortfolioValidator()),
            new ExcelIntegration.TemplateWriter(),
            new MessageBus(),
            new RecentFilesStore());

        typeof(PortfolioWorkspaceService)
            .GetProperty(nameof(PortfolioWorkspaceService.Current))!
            .SetValue(workspace, new PortfolioFile
            {
                FilePath = "C:\\test.xlsx",
                Metadata = new PortfolioMetadata { PortfolioName = "Sec", BaseCurrency = "USD" },
                Holdings = [],
            });

        var engine = new EngineHostService(client);
        typeof(EngineHostService)
            .GetMethod("SetState", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
            .Invoke(engine, [EngineConnectionState.Online, "online"]);

        var nlq = new NlqService(
            bus,
            client,
            session,
            workspace,
            engine,
            new EsgPreferencesService(new EsgPreferencesStore()));

        return (nlq, gen);
    }

    private sealed class StubHandler(Func<HttpRequestMessage, HttpResponseMessage> responder) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken) =>
            Task.FromResult(responder(request));
    }
}
