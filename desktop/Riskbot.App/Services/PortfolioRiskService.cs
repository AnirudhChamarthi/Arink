using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;

namespace Riskbot.App.Services;

/// <summary>Fetches portfolio VaR after enrichment for treemap VaR-contribution mode.</summary>
public sealed class PortfolioRiskService : IAsyncDisposable
{
    private readonly MessageBus _bus;
    private readonly RiskbotApiClient _api;
    private readonly PortfolioSessionState _session;
    private readonly EngineHostService _engine;
    private readonly VarSettingsService _varSettings;
    private readonly SemaphoreSlim _varGate = new(1, 1);
    private CancellationTokenSource? _varCts;

    public PortfolioRiskService(
        MessageBus bus,
        RiskbotApiClient api,
        PortfolioSessionState session,
        EngineHostService engine,
        VarSettingsService varSettings)
    {
        _bus = bus;
        _api = api;
        _session = session;
        _engine = engine;
        _varSettings = varSettings;
        _bus.Subscribe<EnrichmentFinishedEvent>(OnEnrichmentFinishedAsync);
        _varSettings.SettingsChanged += OnVarSettingsChanged;
    }

    private void OnVarSettingsChanged()
    {
        var sessionId = _session.PortfolioSessionId;
        if (string.IsNullOrWhiteSpace(sessionId) || _session.EnrichGeneration <= 0)
            return;

        _ = RefreshVarAsync(_session.EnrichGeneration, sessionId);
    }

    private async Task OnEnrichmentFinishedAsync(EnrichmentFinishedEvent evt)
    {
        if (evt.PositionCount == 0)
            return;

        if (string.IsNullOrWhiteSpace(evt.PortfolioSessionId))
            return;

        if (_engine.State != EngineConnectionState.Online)
            return;

        CancelInFlightVar();

        await _varGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (!_session.Matches(evt.EnrichGeneration, evt.PortfolioSessionId))
                return;

            _varCts = new CancellationTokenSource();
            var ct = _varCts.Token;
            var generation = evt.EnrichGeneration;
            var sessionId = evt.PortfolioSessionId;

            try
            {
                await RefreshVarCoreAsync(generation, sessionId, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Superseded by a newer enrich/VaR request.
            }
            catch (Exception ex)
            {
                if (!_session.Matches(generation, sessionId))
                    return;

                await _bus.PublishAsync(new VarFailedEvent
                {
                    PortfolioSessionId = sessionId,
                    EnrichGeneration = generation,
                    Message = ex.Message,
                }).ConfigureAwait(false);
            }
        }
        finally
        {
            _varGate.Release();
        }
    }

    private async Task RefreshVarAsync(long generation, string sessionId)
    {
        CancelInFlightVar();
        await _varGate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (!_session.Matches(generation, sessionId))
                return;

            _varCts = new CancellationTokenSource();
            await RefreshVarCoreAsync(generation, sessionId, _varCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // Superseded.
        }
        catch (Exception ex)
        {
            if (_session.Matches(generation, sessionId))
            {
                await _bus.PublishAsync(new VarFailedEvent
                {
                    PortfolioSessionId = sessionId,
                    EnrichGeneration = generation,
                    Message = ex.Message,
                }).ConfigureAwait(false);
            }
        }
        finally
        {
            _varGate.Release();
        }
    }

    private async Task RefreshVarCoreAsync(long generation, string sessionId, CancellationToken ct)
    {
        var result = await _api
            .RunVarAsync(
                sessionId,
                _varSettings.Confidence,
                _varSettings.HorizonDays,
                _varSettings.Method,
                ct)
            .ConfigureAwait(false);

        if (!_session.Matches(generation, sessionId))
            return;

        var byTicker = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
        foreach (var c in result.Contributions)
            byTicker[c.Ticker] = c.PctOfTotal * 100.0;

        await _bus.PublishAsync(new VarLoadedEvent
        {
            PortfolioSessionId = sessionId,
            EnrichGeneration = generation,
            ContributionPctByTicker = byTicker,
            PortfolioVar = result.Var,
        }).ConfigureAwait(false);
    }

    private void CancelInFlightVar()
    {
        _varCts?.Cancel();
        _varCts?.Dispose();
        _varCts = null;
    }

    public ValueTask DisposeAsync()
    {
        _varSettings.SettingsChanged -= OnVarSettingsChanged;
        CancelInFlightVar();
        _varGate.Dispose();
        return ValueTask.CompletedTask;
    }
}
