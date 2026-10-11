using System.Collections.ObjectModel;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.ViewModels;

public sealed partial class TreemapViewModel : ObservableObject
{
    private readonly MessageBus _bus;
    private readonly SelectionService _selection;
    private readonly Dictionary<string, TreemapTile> _tilesByTicker = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, EnrichedPositionDto> _positions = new(StringComparer.OrdinalIgnoreCase);
    private long _activeGeneration;

    public TreemapViewModel(MessageBus bus, SelectionService selection)
    {
        _bus = bus;
        _selection = selection;
        _selection.SelectionChanged += OnSelectionChanged;
        _bus.Subscribe<PortfolioLoadedEvent>(OnPortfolioLoadedAsync);
        _bus.Subscribe<EnrichmentStartedEvent>(OnEnrichmentStartedAsync);
        _bus.Subscribe<EnrichmentCompleteEvent>(OnEnrichmentCompleteAsync);
        _bus.Subscribe<EnrichmentFailedEvent>(OnEnrichmentFailedAsync);
        _bus.Subscribe<VarLoadedEvent>(OnVarLoadedAsync);
        _bus.Subscribe<VarFailedEvent>(OnVarFailedAsync);
    }

    public ObservableCollection<TreemapTile> Tiles { get; } = [];

    [ObservableProperty]
    private TreemapMode _mode = TreemapMode.Exposure;

    [ObservableProperty]
    private string _modeLabel = "Exposure (asset class)";

    [ObservableProperty]
    private bool _hasTiles;

    [ObservableProperty]
    private string _emptyMessage = "Load a portfolio to see the treemap.";

    [ObservableProperty]
    private string _statusHint = "";

    [ObservableProperty]
    private IReadOnlyList<TreemapLayoutRect> _layoutRects = [];

    [ObservableProperty]
    private int _layoutTick;

    [RelayCommand]
    private void CycleMode()
    {
        Mode = Mode switch
        {
            TreemapMode.Exposure => TreemapMode.Esg,
            TreemapMode.Esg => TreemapMode.Carbon,
            TreemapMode.Carbon => TreemapMode.VarContribution,
            _ => TreemapMode.Exposure,
        };
        ModeLabel = Mode switch
        {
            TreemapMode.Exposure => "Exposure (asset class)",
            TreemapMode.Esg => "ESG score",
            TreemapMode.Carbon => "Carbon intensity",
            TreemapMode.VarContribution => "VaR contribution",
            _ => "Exposure",
        };
        ApplyColors();
        RequestLayoutRefresh();
    }

    public void SelectTile(TreemapTile tile) => _selection.Select(tile.Ticker);

    public void UpdateLayout(double width, double height)
    {
        if (double.IsNaN(width) || double.IsNaN(height) || width < 4 || height < 4 || Tiles.Count == 0)
        {
            LayoutRects = [];
            return;
        }

        var weights = Tiles.Select(t => Math.Max(t.WeightPercent, 0.01)).ToList();
        var layout = SquarifiedTreemapLayout.Layout(weights, new Rect(0, 0, width, height));
        LayoutRects = layout
            .Select(r => new TreemapLayoutRect { Tile = Tiles[r.Index], Bounds = r.Bounds })
            .ToList();
    }

    public void RequestLayoutRefresh() => LayoutTick++;

    private Task OnPortfolioLoadedAsync(PortfolioLoadedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _activeGeneration = 0;
            _selection.Select(null);
            Tiles.Clear();
            _tilesByTicker.Clear();
            _positions.Clear();
            HasTiles = false;
            LayoutRects = [];
            StatusHint = "";
            EmptyMessage = "Enriching portfolio…";
        }).Task;
    }

    private Task OnEnrichmentStartedAsync(EnrichmentStartedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _activeGeneration = evt.EnrichGeneration;
            StatusHint = "";
            EmptyMessage = "Enriching portfolio…";
        }).Task;
    }

    private Task OnEnrichmentCompleteAsync(EnrichmentCompleteEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            var pos = evt.Position;
            _positions[pos.Ticker] = pos;

            if (!_tilesByTicker.TryGetValue(pos.Ticker, out var tile))
            {
                tile = new TreemapTile { Ticker = pos.Ticker };
                _tilesByTicker[pos.Ticker] = tile;
                Tiles.Add(tile);
            }

            tile.Name = pos.Name;
            tile.AssetClass = pos.AssetClass;
            tile.EsgScore = pos.EsgScore;
            tile.CarbonIntensity = pos.CarbonIntensity;
            tile.VarContributionPct = null;
            tile.IsSelected = string.Equals(_selection.SelectedTicker, pos.Ticker, StringComparison.OrdinalIgnoreCase);

            RecomputeWeightsAndTooltips();
            HasTiles = Tiles.Count > 0;
            EmptyMessage = HasTiles ? "" : "No positions to display.";
            ApplyColors();
            RequestLayoutRefresh();
        }).Task;
    }

    private Task OnEnrichmentFailedAsync(EnrichmentFailedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            HasTiles = false;
            LayoutRects = [];
            StatusHint = "";
            EmptyMessage = $"Enrichment failed: {evt.Message}";
        }).Task;
    }

    private Task OnVarLoadedAsync(VarLoadedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            foreach (var tile in Tiles)
            {
                if (evt.ContributionPctByTicker.TryGetValue(tile.Ticker, out var pct))
                {
                    tile.VarContributionPct = pct;
                    if (_positions.TryGetValue(tile.Ticker, out var pos))
                        tile.Tooltip = BuildTooltip(tile, pos);
                }
            }

            StatusHint = "";
            ApplyColors();
            RequestLayoutRefresh();
        }).Task;
    }

    private Task OnVarFailedAsync(VarFailedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            StatusHint = Mode == TreemapMode.VarContribution
                ? $"VaR unavailable: {evt.Message}"
                : "";
            RequestLayoutRefresh();
        }).Task;
    }

    private void RecomputeWeightsAndTooltips()
    {
        var totalMv = _positions.Values.Sum(MarketValue);
        foreach (var tile in Tiles)
        {
            if (!_positions.TryGetValue(tile.Ticker, out var pos))
                continue;
            tile.WeightPercent = totalMv > 1e-9 ? MarketValue(pos) / totalMv * 100.0 : 0;
            tile.Tooltip = BuildTooltip(tile, pos);
        }
    }

    private void OnSelectionChanged(string? ticker)
    {
        App.Current.Dispatcher.Invoke(() =>
        {
            foreach (var tile in Tiles)
                tile.IsSelected = string.Equals(tile.Ticker, ticker, StringComparison.OrdinalIgnoreCase);
            RequestLayoutRefresh();
        });
    }

    private void ApplyColors()
    {
        foreach (var tile in Tiles)
            tile.FillColor = TreemapColorHelper.ColorFor(tile, Mode);
    }

    private static double MarketValue(EnrichedPositionDto pos) =>
        pos.AssetClass == "Cash" ? pos.Quantity : pos.CurrentPrice * pos.Quantity;

    private static string BuildTooltip(TreemapTile tile, EnrichedPositionDto pos)
    {
        var mv = MarketValue(pos);
        var varLine = tile.VarContributionPct is { } v
            ? $"VaR contribution: {v:N2}% of portfolio VaR"
            : null;
        return string.Join(
            Environment.NewLine,
            new[]
            {
                $"{pos.Ticker} — {pos.Name}",
                $"Asset class: {pos.AssetClass}  |  Sector: {pos.Sector ?? "—"}",
                $"Qty: {pos.Quantity:N2}  @  {pos.CurrentPrice:N2} {pos.Currency}",
                $"Weight: {tile.WeightPercent:N2}%  |  Mkt val: {mv:N0}",
                $"ESG: {pos.EsgScore:N1}  |  Carbon: {pos.CarbonIntensity:N1}  |  Beta: {pos.Beta?.ToString("N2") ?? "—"}",
                varLine,
            }.Where(l => l is not null));
    }
}
