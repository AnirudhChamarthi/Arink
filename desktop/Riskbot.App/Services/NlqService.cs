using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

public sealed class NlqService : IAsyncDisposable
{
    private readonly MessageBus _bus;
    private readonly RiskbotApiClient _api;
    private readonly PortfolioSessionState _session;
    private readonly PortfolioWorkspaceService _workspace;
    private readonly EngineHostService _engine;
    private readonly EsgPreferencesService _esgPrefs;
    private CancellationTokenSource? _nlqCts;

    public NlqService(
        MessageBus bus,
        RiskbotApiClient api,
        PortfolioSessionState session,
        PortfolioWorkspaceService workspace,
        EngineHostService engine,
        EsgPreferencesService esgPrefs)
    {
        _bus = bus;
        _api = api;
        _session = session;
        _workspace = workspace;
        _engine = engine;
        _esgPrefs = esgPrefs;
    }

    public async Task SubmitAsync(string query, long enrichGeneration, CancellationToken cancellationToken = default)
    {
        var trimmed = query.Trim();
        if (trimmed.Length == 0)
            throw new InvalidOperationException("Enter a question first.");

        if (trimmed.Length > NlqErrorSanitizer.MaxQueryLength)
            throw new InvalidOperationException(
                $"Questions must be {NlqErrorSanitizer.MaxQueryLength} characters or fewer.");

        if (_engine.State != EngineConnectionState.Online)
            throw new InvalidOperationException("Engine is offline.");

        var sessionId = _session.PortfolioSessionId;
        if (string.IsNullOrWhiteSpace(sessionId))
            throw new InvalidOperationException("Portfolio is not enriched yet. Wait for enrichment to finish.");

        if (!_session.Matches(enrichGeneration, sessionId))
            throw new InvalidOperationException("Portfolio session expired. Refresh market data and try again.");

        var portfolio = _workspace.Current
            ?? throw new InvalidOperationException("No portfolio is open.");

        _nlqCts?.Cancel();
        _nlqCts?.Dispose();
        _nlqCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var ct = _nlqCts.Token;

        await _bus.PublishAsync(new NlqStartedEvent
        {
            Query = trimmed,
            EnrichGeneration = enrichGeneration,
        }).ConfigureAwait(false);

        var request = new NlqRequestDto
        {
            Query = trimmed,
            PortfolioSessionId = sessionId,
            Limits = RiskLimitsResolver.Resolve(portfolio.Metadata, _esgPrefs.Current),
        };

        try
        {
            var result = await _api.RunNlqAsync(request, ct).ConfigureAwait(false);

            if (!_session.Matches(enrichGeneration, sessionId))
                return;

            if (!NlqReportPathValidator.TryValidate(result.ExcelReportPath, out _))
            {
                await PublishFailureAsync(enrichGeneration, trimmed,
                    "The engine returned an invalid report path.").ConfigureAwait(false);
                return;
            }

            await _bus.PublishAsync(new NlqResultEvent
            {
                Result = result,
                EnrichGeneration = enrichGeneration,
                Query = trimmed,
            }).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            if (_session.Matches(enrichGeneration, sessionId))
            {
                await _bus.PublishAsync(new NlqCancelledEvent
                {
                    EnrichGeneration = enrichGeneration,
                    Query = trimmed,
                }).ConfigureAwait(false);
            }
        }
        catch (Exception ex)
        {
            if (!_session.Matches(enrichGeneration, sessionId))
                return;

            await PublishFailureAsync(enrichGeneration, trimmed, NlqErrorSanitizer.ForUser(ex))
                .ConfigureAwait(false);
        }
    }

    private Task PublishFailureAsync(long enrichGeneration, string query, string message) =>
        _bus.PublishAsync(new NlqFailedEvent
        {
            EnrichGeneration = enrichGeneration,
            Query = query,
            Message = message,
        });

    public ValueTask DisposeAsync()
    {
        _nlqCts?.Cancel();
        _nlqCts?.Dispose();
        _nlqCts = null;
        return ValueTask.CompletedTask;
    }
}
