using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.ViewModels;

public sealed partial class BlotterViewModel : ObservableObject
{
    private readonly MessageBus _bus;
    private readonly SelectionService _selection;
    private readonly RiskLimitMonitorService _limitMonitor;
    private readonly Dictionary<string, BlotterRow> _rowsByTicker = new(StringComparer.OrdinalIgnoreCase);
    private long _activeGeneration;

    public BlotterViewModel(MessageBus bus, SelectionService selection, RiskLimitMonitorService limitMonitor)
    {
        _bus = bus;
        _selection = selection;
        _limitMonitor = limitMonitor;
        _selection.SelectionChanged += OnSelectionChanged;
        _bus.Subscribe<PortfolioLoadedEvent>(OnPortfolioLoadedAsync);
        _bus.Subscribe<EnrichmentStartedEvent>(OnEnrichmentStartedAsync);
        _bus.Subscribe<EnrichmentCompleteEvent>(OnEnrichmentCompleteAsync);
        _bus.Subscribe<EnrichmentFailedEvent>(OnEnrichmentFailedAsync);
        _bus.Subscribe<RiskBreachesUpdatedEvent>(OnRiskBreachesUpdatedAsync);
    }

    public ObservableCollection<BlotterRow> Rows { get; } = [];

    [ObservableProperty]
    private string _statusText = "No portfolio loaded.";

    public event Action<string?>? HighlightTickerRequested;

    public void SelectRow(BlotterRow row) => _selection.Select(row.Ticker);

    public void ClearSelection() => _selection.Select(null);

    private void OnSelectionChanged(string? ticker)
    {
        App.Current.Dispatcher.Invoke(() =>
        {
            foreach (var row in Rows)
                row.IsSelected = string.Equals(row.Ticker, ticker, StringComparison.OrdinalIgnoreCase);
            HighlightTickerRequested?.Invoke(ticker);
        });
    }

    private Task OnPortfolioLoadedAsync(PortfolioLoadedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _activeGeneration = 0;
            _selection.Select(null);
            Rows.Clear();
            _rowsByTicker.Clear();
            foreach (var h in evt.Portfolio.Holdings)
            {
                var row = BlotterRow.FromHolding(h);
                Rows.Add(row);
                _rowsByTicker[row.Ticker] = row;
            }
            _limitMonitor.SetLimitsFromWorkspace();
            foreach (var row in Rows)
            {
                row.HasBreach = false;
                row.BreachSummary = "";
            }
            StatusText = $"{Rows.Count} positions — enriching…";
        }).Task;
    }

    private Task OnEnrichmentStartedAsync(EnrichmentStartedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _activeGeneration = evt.EnrichGeneration;
            StatusText = $"Enriching {evt.PortfolioName}…";
        }).Task;
    }

    private Task OnEnrichmentCompleteAsync(EnrichmentCompleteEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            if (_rowsByTicker.TryGetValue(evt.Position.Ticker, out var row))
            {
                var totalMv = Rows.Sum(r =>
                    r.Ticker == evt.Position.Ticker
                        ? EstimateMarketValue(evt.Position)
                        : r.MarketValue ?? r.CostPrice * r.Quantity);
                if (totalMv <= 0) totalMv = 1.0;
                row.ApplyEnrichment(evt.Position, totalMv);
            }

            if (evt.Index + 1 >= evt.Total)
            {
                var portfolioMv = Rows.Sum(r => r.MarketValue ?? 0);
                if (portfolioMv > 0)
                {
                    foreach (var r in Rows)
                    {
                        if (r.MarketValue is { } mv)
                            r.WeightPercent = mv / portfolioMv * 100.0;
                    }
                }
                StatusText = $"Enriched {evt.Total} positions";
            }
            else
            {
                StatusText = $"Enriching {evt.Index + 1} / {evt.Total}…";
            }

            _limitMonitor.SyncRows(Rows);
            _ = _limitMonitor.RefreshAsync(_activeGeneration);
        }).Task;
    }

    private Task OnRiskBreachesUpdatedAsync(RiskBreachesUpdatedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            foreach (var row in Rows)
            {
                if (evt.PositionBreaches.TryGetValue(row.Ticker, out var reasons))
                {
                    row.HasBreach = true;
                    row.BreachSummary = FormatBreachReasons(reasons);
                }
                else
                {
                    row.HasBreach = false;
                    row.BreachSummary = "";
                }
            }

            var baseStatus = Rows.Count > 0 && Rows[0].CurrentPrice is not null
                ? $"Enriched {Rows.Count} positions"
                : StatusText;

            if (evt.PortfolioBreaches.Count > 0)
            {
                var flags = string.Join(", ", evt.PortfolioBreaches.Select(FormatPortfolioBreach));
                StatusText = $"{baseStatus} — limit breach: {flags}";
            }
            else if (evt.PositionBreaches.Count > 0)
            {
                StatusText = $"{baseStatus} — {evt.PositionBreaches.Count} position(s) in breach";
            }
        }).Task;
    }

    private static string FormatBreachReasons(IReadOnlyList<string> codes) =>
        string.Join(", ", codes.Select(c => c switch
        {
            RiskLimitMonitor.Concentration => "concentration",
            RiskLimitMonitor.Exclusion => "exclusion",
            RiskLimitMonitor.EsgPosition => "ESG",
            _ => c,
        }));

    private static string FormatPortfolioBreach(string code) => code switch
    {
        RiskLimitMonitor.VarLimit => "VaR",
        RiskLimitMonitor.PortfolioEsg => "portfolio ESG",
        _ => code,
    };

    private Task OnEnrichmentFailedAsync(EnrichmentFailedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;
            StatusText = $"Enrichment failed: {evt.Message}";
        }).Task;
    }

    private static double EstimateMarketValue(ApiClient.EnrichedPositionDto pos) =>
        pos.AssetClass == "Cash" ? pos.Quantity : pos.CurrentPrice * pos.Quantity;
}
