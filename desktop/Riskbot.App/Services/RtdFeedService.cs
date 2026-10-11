using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Models;
using Riskbot.RtdBridge;

namespace Riskbot.App.Services;

/// <summary>Pushes live blotter metrics to the RTD snapshot file for the Excel-DNA add-in.</summary>
public sealed class RtdFeedService
{
    private readonly MessageBus _bus;
    private readonly PortfolioWorkspaceService _workspace;
    private readonly PortfolioSessionState _session;
    private readonly EngineHostService _engine;
    private readonly RiskbotApiClient _api;
    private readonly object _lock = new();
    private RtdSnapshot _snapshot = new();
    private long _generation;

    public RtdFeedService(
        MessageBus bus,
        PortfolioWorkspaceService workspace,
        PortfolioSessionState session,
        EngineHostService engine,
        RiskbotApiClient api)
    {
        _bus = bus;
        _workspace = workspace;
        _session = session;
        _engine = engine;
        _api = api;

        _bus.Subscribe<PortfolioLoadedEvent>(_ => { Clear(); return Task.CompletedTask; });
        _bus.Subscribe<EnrichmentStartedEvent>(e =>
        {
            _generation = e.EnrichGeneration;
            return Task.CompletedTask;
        });
        _bus.Subscribe<EnrichmentCompleteEvent>(OnEnrichmentCompleteAsync);
        _bus.Subscribe<EnrichmentFinishedEvent>(OnEnrichmentFinishedAsync);
        _bus.Subscribe<VarLoadedEvent>(OnVarLoadedAsync);
    }

    public string SnapshotPath => RtdSnapshotFile.DefaultPath;

    public RtdSnapshot GetSnapshot()
    {
        lock (_lock)
            return CloneSnapshot(_snapshot);
    }

    private Task OnEnrichmentCompleteAsync(EnrichmentCompleteEvent evt)
    {
        if (evt.EnrichGeneration != _generation)
            return Task.CompletedTask;

        var portfolio = _workspace.Current;
        if (portfolio is null)
            return Task.CompletedTask;

        var holdings = portfolio.Holdings.ToDictionary(h => h.Ticker, StringComparer.OrdinalIgnoreCase);
        if (!holdings.TryGetValue(evt.Position.Ticker, out var holding))
            return Task.CompletedTask;

        var positions = _session.DisplayPortfolio?.Positions ?? [];
        var totalMv = positions.Sum(p =>
            p.AssetClass == "Cash" ? p.Quantity : p.CurrentPrice * p.Quantity);
        if (totalMv <= 0)
            totalMv = 1.0;

        var pos = evt.Position;
        var mv = pos.AssetClass == "Cash" ? pos.Quantity : pos.CurrentPrice * pos.Quantity;
        var cost = holding.CostPrice * holding.Quantity;
        var pnl = mv - cost;
        var pnlPct = cost > 1e-9 ? pnl / cost * 100.0 : 0.0;
        var weight = mv / totalMv * 100.0;

        lock (_lock)
        {
            _snapshot.PortfolioName = portfolio.Metadata.PortfolioName;
            var t = pos.Ticker;
            _snapshot.SetValue(t, RtdFields.CurrentPrice, pos.CurrentPrice);
            _snapshot.SetValue(t, RtdFields.MarketValue, mv);
            _snapshot.SetValue(t, RtdFields.PnL, pnl);
            _snapshot.SetValue(t, RtdFields.PnLPct, pnlPct);
            _snapshot.SetValue(t, RtdFields.WeightPct, weight);
            if (pos.Beta is not null)
                _snapshot.SetValue(t, RtdFields.Beta, pos.Beta.Value);
            _snapshot.SetValue(t, RtdFields.EsgScore, pos.EsgScore);
            _snapshot.SetValue(t, RtdFields.CarbonIntensity, pos.CarbonIntensity);
        }

        Flush();
        return Task.CompletedTask;
    }

    private async Task OnEnrichmentFinishedAsync(EnrichmentFinishedEvent evt)
    {
        if (evt.EnrichGeneration != _generation)
            return;

        if (_engine.State != EngineConnectionState.Online
            || string.IsNullOrWhiteSpace(evt.PortfolioSessionId))
            return;

        try
        {
            var greeks = await _api.RunGreeksAsync(evt.PortfolioSessionId).ConfigureAwait(false);
            lock (_lock)
            {
                foreach (var p in greeks.Positions)
                    _snapshot.SetValue(p.Ticker, RtdFields.Delta, p.Delta);
            }
            Flush();
        }
        catch
        {
            // Greeks optional for RTD — prices still flow.
        }
    }

    private Task OnVarLoadedAsync(VarLoadedEvent evt)
    {
        if (evt.EnrichGeneration != _generation)
            return Task.CompletedTask;

        lock (_lock)
        {
            foreach (var (ticker, pct) in evt.ContributionPctByTicker)
                _snapshot.SetValue(ticker, RtdFields.VarContributionPct, pct);
        }

        Flush();
        return Task.CompletedTask;
    }

    private void Clear()
    {
        lock (_lock)
            _snapshot = new RtdSnapshot();
        Flush();
    }

    private void Flush()
    {
        RtdSnapshot copy;
        lock (_lock)
            copy = CloneSnapshot(_snapshot);
        RtdSnapshotFile.Write(SnapshotPath, copy);
    }

    private static RtdSnapshot CloneSnapshot(RtdSnapshot source) =>
        new()
        {
            UpdatedUtc = source.UpdatedUtc,
            PortfolioName = source.PortfolioName,
            Topics = new Dictionary<string, double>(source.Topics, StringComparer.OrdinalIgnoreCase),
        };
}
