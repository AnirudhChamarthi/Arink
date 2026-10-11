using Riskbot.App.ApiClient;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Helpers;

/// <summary>Merges portfolio metadata limits with user ESG preferences.</summary>
public static class RiskLimitsResolver
{
    public static RiskLimitsDto Resolve(PortfolioMetadata? metadata, EsgPreferences userPrefs)
    {
        var dto = metadata is null
            ? new RiskLimitsDto()
            : RiskLimitsMapper.FromMetadata(metadata);

        var mergedFilters = new List<string>();
        mergedFilters.AddRange(ExclusionPolicy.ToFilterTokens(userPrefs));
        if (metadata?.ExclusionFilters is { } fileFilters && !string.IsNullOrWhiteSpace(fileFilters))
        {
            mergedFilters.AddRange(
                fileFilters.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries));
        }

        dto.ExclusionFilters = mergedFilters
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(EsgPreferencesValidator.MaxMergedExclusionTokens)
            .ToList();

        if (userPrefs.EsgMinScore is not null)
            dto.EsgMinScore = userPrefs.EsgMinScore;

        return dto;
    }
}
