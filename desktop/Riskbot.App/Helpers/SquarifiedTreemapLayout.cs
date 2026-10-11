using System.Windows;

namespace Riskbot.App.Helpers;

public static class SquarifiedTreemapLayout
{
    public sealed record LayoutRect(int Index, Rect Bounds);

    public static IReadOnlyList<LayoutRect> Layout(IReadOnlyList<double> weights, Rect area)
    {
        var w = Math.Max(0, area.Width);
        var h = Math.Max(0, area.Height);
        if (weights.Count == 0 || w < 1 || h < 1)
            return [];

        var total = weights.Sum();
        if (total <= 0)
            return [];

        var items = weights
            .Select((weight, i) => (Index: i, Value: weight / total * w * h))
            .OrderByDescending(x => x.Value)
            .ToList();

        var rects = new List<LayoutRect>();
        Squarify(items, new Rect(area.X, area.Y, w, h), rects);
        return rects;
    }

    private static void Squarify(List<(int Index, double Value)> items, Rect container, List<LayoutRect> output)
    {
        const double minDim = 1.0;

        while (items.Count > 0 && container.Width >= minDim && container.Height >= minDim)
        {
            var horizontal = container.Width >= container.Height;
            var length = Math.Max(minDim, horizontal ? container.Height : container.Width);
            var row = new List<(int Index, double Value)>();
            var sum = 0.0;

            while (items.Count > 0)
            {
                row.Add(items[0]);
                var newSum = sum + items[0].Value;
                if (row.Count > 1 && Worst(row, length, newSum) > Worst(row, length, sum))
                {
                    row.RemoveAt(row.Count - 1);
                    break;
                }

                sum += items[0].Value;
                items.RemoveAt(0);
            }

            if (row.Count == 0 || sum <= 0)
                break;

            var rowThickness = Math.Min(sum / length, horizontal ? container.Width : container.Height);
            if (rowThickness < minDim)
                break;

            var offset = 0.0;
            foreach (var item in row)
            {
                var slice = Math.Max(minDim, item.Value / rowThickness);
                if (horizontal)
                {
                    var rectW = rowThickness;
                    var rectH = Math.Min(slice, container.Height - offset);
                    if (rectW >= minDim && rectH >= minDim)
                        output.Add(new LayoutRect(item.Index, new Rect(container.X, container.Y + offset, rectW, rectH)));
                    offset += slice;
                }
                else
                {
                    var rectW = Math.Min(slice, container.Width - offset);
                    var rectH = rowThickness;
                    if (rectW >= minDim && rectH >= minDim)
                        output.Add(new LayoutRect(item.Index, new Rect(container.X + offset, container.Y, rectW, rectH)));
                    offset += slice;
                }
            }

            container = horizontal
                ? new Rect(
                    container.X + rowThickness,
                    container.Y,
                    Math.Max(0, container.Width - rowThickness),
                    container.Height)
                : new Rect(
                    container.X,
                    container.Y + rowThickness,
                    container.Width,
                    Math.Max(0, container.Height - rowThickness));
        }
    }

    private static double Worst(List<(int Index, double Value)> row, double length, double sum)
    {
        if (sum <= 0)
            return double.MaxValue;
        var max = row.Max(x => x.Value);
        var min = row.Min(x => x.Value);
        var s2 = sum * sum;
        return Math.Max(length * length * max / s2, s2 / (length * length * min));
    }
}
