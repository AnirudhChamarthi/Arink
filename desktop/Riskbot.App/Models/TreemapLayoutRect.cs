using System.Windows;

namespace Riskbot.App.Models;

public sealed class TreemapLayoutRect
{
    public required TreemapTile Tile { get; init; }
    public Rect Bounds { get; init; }
}
