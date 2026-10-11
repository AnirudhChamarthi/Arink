using Riskbot.App.ApiClient;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class RiskLimitMonitorTests
{
    [Fact]
    public void Concentration_breach_when_weight_exceeds_limit()
    {
        var rows = new List<BlotterRow>
        {
            new() { Ticker = "AAPL", WeightPercent = 20.0, Sector = "Technology", EsgScore = 80 },
            new() { Ticker = "MSFT", WeightPercent = 5.0, Sector = "Technology", EsgScore = 80 },
        };
        var limits = new RiskLimitsDto { MaxConcentration = 0.15 };

        var result = RiskLimitMonitor.Evaluate(rows, limits, null, null);

        Assert.True(result.PositionBreaches.ContainsKey("AAPL"));
        Assert.Contains(RiskLimitMonitor.Concentration, result.PositionBreaches["AAPL"]);
        Assert.False(result.PositionBreaches.ContainsKey("MSFT"));
    }

    [Fact]
    public void Var_limit_portfolio_breach()
    {
        var limits = new RiskLimitsDto { VarLimit = 0.05 };
        var result = RiskLimitMonitor.Evaluate([], limits, portfolioVarDecimal: 0.06, null);

        Assert.Contains(RiskLimitMonitor.VarLimit, result.PortfolioBreaches);
    }

    [Fact]
    public void Exclusion_matches_ticker_not_sector_preset()
    {
        var hits = ExclusionChecker.MatchingFilters(
            "PLTR", "Palantir", "Technology", ["ticker:PLTR"]);
        Assert.Contains("ticker:PLTR", hits);
        Assert.Empty(ExclusionChecker.MatchingFilters("BA", "Boeing", "Aerospace", ["ticker:PLTR"]));
    }

    [Fact]
    public void Esg_position_breach_when_below_min()
    {
        var rows = new List<BlotterRow>
        {
            new() { Ticker = "XOM", WeightPercent = 10, Sector = "Energy", EsgScore = 35 },
        };
        var limits = new RiskLimitsDto { EsgMinScore = 40 };

        var result = RiskLimitMonitor.Evaluate(rows, limits, null, null);

        Assert.Contains(RiskLimitMonitor.EsgPosition, result.PositionBreaches["XOM"]);
    }
}
