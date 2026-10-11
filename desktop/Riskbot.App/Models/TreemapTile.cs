using System.Windows.Media;

namespace Riskbot.App.Models;

public sealed class TreemapTile
{
    public required string Ticker { get; init; }
    public string Name { get; set; } = "";
    public string AssetClass { get; set; } = "";
    public double WeightPercent { get; set; }
    public double? EsgScore { get; set; }
    public double? CarbonIntensity { get; set; }
    public double? VarContributionPct { get; set; }
    public string Tooltip { get; set; } = "";

    public Color FillColor { get; set; } = Colors.SteelBlue;
    public bool IsSelected { get; set; }
}
