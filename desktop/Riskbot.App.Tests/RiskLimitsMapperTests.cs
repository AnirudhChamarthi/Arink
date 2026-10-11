using Riskbot.App.ApiClient;
using Riskbot.App.Helpers;
using Riskbot.App.Models;

namespace Riskbot.App.Tests;

public class RiskLimitsMapperTests
{
    [Fact]
    public void FromMetadata_maps_limits_and_exclusion_filters()
    {
        var dto = RiskLimitsMapper.FromMetadata(new PortfolioMetadata
        {
            PortfolioName = "Book",
            BaseCurrency = "USD",
            VarLimit = 0.05,
            MaxConcentration = 0.15,
            ExclusionFilters = "weapons, tobacco , gambling",
        });

        Assert.Equal(0.05, dto.VarLimit);
        Assert.Equal(0.15, dto.MaxConcentration);
        Assert.Equal(3, dto.ExclusionFilters.Count);
        Assert.Contains("weapons", dto.ExclusionFilters);
        Assert.Contains("tobacco", dto.ExclusionFilters);
        Assert.Contains("gambling", dto.ExclusionFilters);
    }
}
