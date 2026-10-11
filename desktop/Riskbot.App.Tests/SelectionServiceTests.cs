using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class SelectionServiceTests
{
    [Fact]
    public void Select_notifies_subscribers()
    {
        var svc = new SelectionService();
        string? seen = "unset";
        svc.SelectionChanged += t => seen = t;

        svc.Select("AAPL");

        Assert.Equal("AAPL", seen);
        Assert.Equal("AAPL", svc.SelectedTicker);
    }

    [Fact]
    public void Select_null_clears_selection()
    {
        var svc = new SelectionService();
        svc.Select("MSFT");
        string? seen = "unset";
        svc.SelectionChanged += t => seen = t;

        svc.Select(null);

        Assert.Null(seen);
        Assert.Null(svc.SelectedTicker);
    }
}
