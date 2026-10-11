using Riskbot.App.ApiClient;
using Riskbot.App.Models;

namespace Riskbot.App.Helpers;

public static class RiskLimitsMapper
{
    public static RiskLimitsDto FromMetadata(PortfolioMetadata metadata)
    {
        var filters = string.IsNullOrWhiteSpace(metadata.ExclusionFilters)
            ? []
            : metadata.ExclusionFilters
                .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
                .ToList();

        return new RiskLimitsDto
        {
            VarLimit = metadata.VarLimit,
            MaxConcentration = metadata.MaxConcentration,
            EsgMinScore = metadata.EsgMinScore,
            ExclusionFilters = filters,
        };
    }
}
