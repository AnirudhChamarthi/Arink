using System.Windows.Media;
using Riskbot.App.Models;

namespace Riskbot.App.Helpers;

public static class TreemapColorHelper
{
    private static readonly Dictionary<string, Color> AssetClassColors = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Equity"] = Color.FromRgb(0x4F, 0xC3, 0xF7),
        ["FixedIncome"] = Color.FromRgb(0xFF, 0xB7, 0x4D),
        ["Commodity"] = Color.FromRgb(0xCE, 0x93, 0xD8),
        ["Cash"] = Color.FromRgb(0x90, 0xA4, 0xAE),
    };

    public static Color ColorFor(TreemapTile tile, TreemapMode mode)
    {
        return mode switch
        {
            TreemapMode.Exposure => AssetClassColors.GetValueOrDefault(tile.AssetClass, Color.FromRgb(0x60, 0x60, 0x60)),
            TreemapMode.Esg => Gradient(tile.EsgScore ?? 50, lowIsGood: false),
            TreemapMode.Carbon => Gradient(tile.CarbonIntensity ?? 50, lowIsGood: true),
            TreemapMode.VarContribution => Gradient(tile.VarContributionPct ?? 0, lowIsGood: false, max: 40),
            _ => Colors.Gray,
        };
    }

    private static Color Gradient(double value, bool lowIsGood, double max = 100)
    {
        var t = Math.Clamp(value / max, 0, 1);
        if (lowIsGood)
            t = 1 - t;
        return Lerp(Color.FromRgb(0x2E, 0x7D, 0x32), Color.FromRgb(0xC6, 0x28, 0x28), t);
    }

    private static Color Lerp(Color a, Color b, double t)
    {
        byte L(byte x, byte y) => (byte)(x + (y - x) * t);
        return Color.FromRgb(L(a.R, b.R), L(a.G, b.G), L(a.B, b.B));
    }
}
