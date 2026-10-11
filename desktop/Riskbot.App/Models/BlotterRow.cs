using System.Windows.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using Riskbot.App.ApiClient;

namespace Riskbot.App.Models;

public sealed partial class BlotterRow : ObservableObject
{
    [ObservableProperty]
    private string _ticker = "";

    [ObservableProperty]
    private string _name = "";

    [ObservableProperty]
    private string _assetClass = "";

    [ObservableProperty]
    private string? _sector;

    [ObservableProperty]
    private double _quantity;

    [ObservableProperty]
    private double _costPrice;

    [ObservableProperty]
    private string _currency = "";

    [ObservableProperty]
    private string? _country;

    [ObservableProperty]
    private string? _isin;

    [ObservableProperty]
    private double? _esgOverride;

    [ObservableProperty]
    private DateOnly? _positionDate;

    [ObservableProperty]
    private double? _currentPrice;

    [ObservableProperty]
    private double? _marketValue;

    [ObservableProperty]
    private double? _pnl;

    [ObservableProperty]
    private double? _pnlPercent;

    [ObservableProperty]
    private double? _weightPercent;

    [ObservableProperty]
    private double? _beta;

    [ObservableProperty]
    private double? _esgScore;

    [ObservableProperty]
    private double? _carbonIntensity;

    [ObservableProperty]
    private string? _activeFlashKey;

    [ObservableProperty]
    private Brush? _flashBackground;

    [ObservableProperty]
    private bool _isSelected;

    [ObservableProperty]
    private bool _hasBreach;

    [ObservableProperty]
    private string _breachSummary = "";

    public static BlotterRow FromHolding(HoldingLine h) => new()
    {
        Ticker = h.Ticker,
        AssetClass = h.AssetClass,
        Sector = h.Sector,
        Quantity = h.Quantity,
        CostPrice = h.CostPrice,
        Currency = h.Currency,
        Country = h.Country,
        Isin = h.Isin,
        EsgOverride = h.EsgOverride,
        PositionDate = h.Date,
    };

    public void ApplyEnrichment(EnrichedPositionDto pos, double portfolioMarketValue)
    {
        if (!string.IsNullOrEmpty(pos.Name))
            UpdateString(nameof(Name), pos.Name);

        UpdateDouble(nameof(CurrentPrice), CurrentPrice, pos.CurrentPrice);

        var mv = pos.AssetClass == "Cash" ? pos.Quantity : pos.CurrentPrice * pos.Quantity;
        UpdateDouble(nameof(MarketValue), MarketValue, mv);

        var cost = pos.CostPrice * pos.Quantity;
        var pnl = mv - cost;
        UpdateDouble(nameof(Pnl), Pnl, pnl);

        var pnlPct = cost > 1e-9 ? (pnl / cost) * 100.0 : 0.0;
        UpdateDouble(nameof(PnlPercent), PnlPercent, pnlPct);

        var weight = portfolioMarketValue > 1e-9 ? (mv / portfolioMarketValue) * 100.0 : 0.0;
        UpdateDouble(nameof(WeightPercent), WeightPercent, weight);

        if (pos.Beta is not null)
            UpdateDouble(nameof(Beta), Beta, pos.Beta.Value);

        UpdateDouble(nameof(EsgScore), EsgScore, pos.EsgScore);
        UpdateDouble(nameof(CarbonIntensity), CarbonIntensity, pos.CarbonIntensity);
    }

    private void UpdateString(string key, string newValue)
    {
        if (string.Equals(Name, newValue, StringComparison.Ordinal))
            return;
        Name = newValue;
        TriggerFlash(key, positive: true);
    }

    private void UpdateDouble(string key, double? oldValue, double newValue)
    {
        if (oldValue is not null && Math.Abs(oldValue.Value - newValue) < 1e-9)
            return;

        var positive = oldValue is null || newValue >= oldValue.Value;
        switch (key)
        {
            case nameof(CurrentPrice): CurrentPrice = newValue; break;
            case nameof(MarketValue): MarketValue = newValue; break;
            case nameof(Pnl): Pnl = newValue; break;
            case nameof(PnlPercent): PnlPercent = newValue; break;
            case nameof(WeightPercent): WeightPercent = newValue; break;
            case nameof(Beta): Beta = newValue; break;
            case nameof(EsgScore): EsgScore = newValue; break;
            case nameof(CarbonIntensity): CarbonIntensity = newValue; break;
        }
        TriggerFlash(key, positive);
    }

    public async void TriggerFlash(string propertyKey, bool positive)
    {
        ActiveFlashKey = propertyKey;
        FlashBackground = new SolidColorBrush(positive
            ? Color.FromRgb(0x2E, 0x7D, 0x32)
            : Color.FromRgb(0xC6, 0x28, 0x28));
        try
        {
            await Task.Delay(400).ConfigureAwait(true);
        }
        finally
        {
            ActiveFlashKey = null;
            FlashBackground = null;
        }
    }
}
