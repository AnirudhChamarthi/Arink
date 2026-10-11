using Riskbot.App.ApiClient;
using Riskbot.App.Helpers;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class RiskLimitsResolverTests
{
    [Fact]
    public void Merges_user_tickers_with_portfolio_metadata_filters()
    {
        var meta = new PortfolioMetadata
        {
            PortfolioName = "Test",
            BaseCurrency = "USD",
            ExclusionFilters = "fossil_fuels",
        };
        var user = new EsgPreferences { ExcludedTickers = ["PLTR"] };

        var dto = RiskLimitsResolver.Resolve(meta, user);

        Assert.Contains("ticker:PLTR", dto.ExclusionFilters);
        Assert.Contains("fossil_fuels", dto.ExclusionFilters);
    }

    [Fact]
    public void User_esg_min_overrides_metadata_only_when_set()
    {
        var meta = new PortfolioMetadata
        {
            PortfolioName = "Test",
            BaseCurrency = "USD",
            EsgMinScore = 50,
        };
        var user = new EsgPreferences { EsgMinScore = 40 };

        var dto = RiskLimitsResolver.Resolve(meta, user);
        Assert.Equal(40, dto.EsgMinScore);
    }
}
