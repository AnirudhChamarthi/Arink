using System.Diagnostics;
using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;

namespace Riskbot.App.Services;

/// <summary>Menu-driven risk analysis (stress, full report) via engine /risk/* endpoints.</summary>
public sealed class RiskAnalysisService
{
    private readonly MessageBus _bus;
    private readonly RiskbotApiClient _api;
    private readonly PortfolioSessionState _session;
    private readonly PortfolioWorkspaceService _workspace;
    private readonly EngineHostService _engine;
    private readonly VarSettingsService _varSettings;
    private readonly EsgPreferencesService _esgPrefs;

    public RiskAnalysisService(
        MessageBus bus,
        RiskbotApiClient api,
        PortfolioSessionState session,
        PortfolioWorkspaceService workspace,
        EngineHostService engine,
        VarSettingsService varSettings,
        EsgPreferencesService esgPrefs)
    {
        _bus = bus;
        _api = api;
        _session = session;
        _workspace = workspace;
        _engine = engine;
        _varSettings = varSettings;
        _esgPrefs = esgPrefs;
    }

    public async Task RunStressAsync(string scenario, CancellationToken cancellationToken = default)
    {
        var sessionId = RequireSession();
        await _bus.PublishAsync(new NlqStartedEvent
        {
            Query = $"Stress: {scenario}",
            EnrichGeneration = _session.EnrichGeneration,
        }).ConfigureAwait(false);

        try
        {
            var result = await _api.RunStressAsync(sessionId, scenario, cancellationToken).ConfigureAwait(false);
            var pct = result.PortfolioPct * 100.0;
            NlqReportPathValidator.TryValidate(result.ExcelReportPath, out var safeExcelPath);
            var nlq = new NlqResultDto
            {
                ToplineNumber = $"{pct:F2}%",
                ToplineLabel = $"Stressed P&L ({result.Scenario})",
                Explanation =
                    $"Portfolio P&L under {result.Scenario}: {result.PortfolioPnl:N0} ({pct:F2}% of MV). " +
                    $"Worst: {string.Join(", ", result.WorstPositions.Select(w => w.Ticker))}.",
                FormulaBreakdown =
                [
                    $"Scenario: {result.Scenario}",
                    $"Portfolio P&L = {result.PortfolioPnl:N0}",
                    ..result.WorstPositions.Select(w =>
                        $"  {w.Ticker}: {w.PctImpact * 100:F2}% of portfolio"),
                ],
                ModelsUsed = [$"stress:{result.Scenario}"],
                ExcelReportPath = safeExcelPath ?? "",
            };

            await _bus.PublishAsync(new NlqResultEvent
            {
                Result = nlq,
                EnrichGeneration = _session.EnrichGeneration,
                Query = $"Stress: {scenario}",
            }).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            await _bus.PublishAsync(new NlqFailedEvent
            {
                EnrichGeneration = _session.EnrichGeneration,
                Query = $"Stress: {scenario}",
                Message = ex.Message,
            }).ConfigureAwait(false);
        }
    }

    public async Task RunFullReportAsync(CancellationToken cancellationToken = default)
    {
        var sessionId = RequireSession();
        var generation = _session.EnrichGeneration;
        var limits = RiskLimitsResolver.Resolve(_workspace.Current?.Metadata, _esgPrefs.Current);

        await _bus.PublishAsync(new NlqStartedEvent
        {
            Query = "Full risk report",
            EnrichGeneration = generation,
        }).ConfigureAwait(false);

        try
        {
            var result = await _api.RunFullReportAsync(
                new FullReportRequestDto
                {
                    PortfolioSessionId = sessionId,
                    Method = _varSettings.Method,
                    Confidence = _varSettings.Confidence,
                    HorizonDays = _varSettings.HorizonDays,
                    ExclusionFilters = limits.ExclusionFilters,
                },
                cancellationToken).ConfigureAwait(false);

            if (!NlqReportPathValidator.TryValidate(result.ExcelReportPath, out var safePath))
                throw new InvalidOperationException(
                    "Full risk report was generated but the file path is not in the allowed reports folder.");

            var topline = ExtractToplineVar(result.SummaryText);
            var nlq = new NlqResultDto
            {
                ToplineNumber = topline,
                ToplineLabel = $"Full risk — {result.PortfolioName}",
                Explanation = result.SummaryText,
                ExcelReportPath = safePath!,
                FormulaBreakdown = result.SummaryText
                    .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .ToList(),
                ModelsUsed =
                [
                    $"var:{_varSettings.Method}",
                    "greeks",
                    "sustainability",
                    "stress",
                ],
            };

            await _bus.PublishAsync(new NlqResultEvent
            {
                Result = nlq,
                EnrichGeneration = generation,
                Query = "Full risk report",
            }).ConfigureAwait(false);

            Process.Start(new ProcessStartInfo(safePath!) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            await _bus.PublishAsync(new NlqFailedEvent
            {
                EnrichGeneration = generation,
                Query = "Full risk report",
                Message = NlqErrorSanitizer.ForUser(ex),
            }).ConfigureAwait(false);
            throw;
        }
    }

    private static string ExtractToplineVar(string summary)
    {
        foreach (var line in summary.Split('\n'))
        {
            var trimmed = line.Trim();
            if (!trimmed.StartsWith("VaR", StringComparison.OrdinalIgnoreCase))
                continue;
            var colon = trimmed.LastIndexOf(':');
            if (colon >= 0 && colon < trimmed.Length - 1)
                return trimmed[(colon + 1)..].Trim();
        }

        return "—";
    }

    private string RequireSession()
    {
        if (_engine.State != EngineConnectionState.Online)
            throw new InvalidOperationException("Engine is offline.");

        var sessionId = _session.PortfolioSessionId;
        if (string.IsNullOrWhiteSpace(sessionId))
            throw new InvalidOperationException("Portfolio is not enriched yet. Wait for enrichment to finish.");

        return sessionId;
    }
}
