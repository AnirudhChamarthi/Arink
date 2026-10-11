using System.Windows;
using Riskbot.App.Helpers;

namespace Riskbot.App.Tests;

public class SquarifiedTreemapLayoutTests
{
    [Fact]
    public void Layout_returns_one_rect_per_position()
    {
        var rects = SquarifiedTreemapLayout.Layout([60, 40], new Rect(0, 0, 100, 100));
        Assert.Equal(2, rects.Count);
        Assert.Equal(0, rects[0].Index);
        Assert.Equal(1, rects[1].Index);
    }

    [Fact]
    public void Layout_empty_or_zero_area_returns_empty()
    {
        Assert.Empty(SquarifiedTreemapLayout.Layout([], new Rect(0, 0, 100, 100)));
        Assert.Empty(SquarifiedTreemapLayout.Layout([50], new Rect(0, 0, 0, 100)));
    }

    [Fact]
    public void Layout_never_produces_negative_dimensions()
    {
        var area = new Rect(0, 0, 120, 48);
        var weights = Enumerable.Range(0, 5).Select(i => (double)(i + 1) * 10).ToList();
        var rects = SquarifiedTreemapLayout.Layout(weights, area);
        Assert.NotEmpty(rects);
        foreach (var r in rects)
        {
            Assert.True(r.Bounds.Width >= 0, $"width {r.Bounds.Width}");
            Assert.True(r.Bounds.Height >= 0, $"height {r.Bounds.Height}");
        }
    }

    [Fact]
    public void Layout_covers_full_area()
    {
        var area = new Rect(0, 0, 200, 100);
        var rects = SquarifiedTreemapLayout.Layout([25, 25, 25, 25], area);
        Assert.Equal(4, rects.Count);
        var covered = rects.Sum(r => r.Bounds.Width * r.Bounds.Height);
        Assert.InRange(covered, area.Width * area.Height * 0.99, area.Width * area.Height * 1.01);
    }
}
