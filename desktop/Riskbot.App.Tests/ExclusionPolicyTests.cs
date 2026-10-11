using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class ExclusionPolicyTests
{
    [Fact]
    public void Ticker_exclusion_flags_only_listed_symbol()
    {
        var filters = ExclusionPolicy.ToFilterTokens(new EsgPreferences
        {
            ExcludedTickers = ["PLTR"],
        });

        Assert.Contains(ExclusionPolicy.MatchingFilters("PLTR", "Palantir", "Technology", filters), f => f.StartsWith("ticker:"));
        Assert.Empty(ExclusionPolicy.MatchingFilters("BA", "Boeing", "Aerospace", filters));
    }

    [Fact]
    public void Weapons_preset_not_enabled_skips_aerospace()
    {
        var filters = ExclusionPolicy.ToFilterTokens(new EsgPreferences
        {
            ExcludedTickers = ["PLTR"],
        });

        Assert.Empty(ExclusionPolicy.MatchingFilters("BA", "Boeing", "Aerospace & Defense", filters));
    }

    [Fact]
    public void Weapons_preset_enabled_flags_boeing()
    {
        var filters = ExclusionPolicy.ToFilterTokens(new EsgPreferences
        {
            EnabledPresets = ["weapons"],
        });

        Assert.Contains("weapons", ExclusionPolicy.MatchingFilters("BA", "Boeing", "Aerospace", filters));
    }

    [Fact]
    public void Name_keyword_matches_company_name()
    {
        var filters = ExclusionPolicy.ToFilterTokens(new EsgPreferences
        {
            ExcludedNameKeywords = ["palantir"],
        });

        Assert.Contains("name:palantir",
            ExclusionPolicy.MatchingFilters("PLTR", "Palantir Technologies", "Technology", filters));
    }
}
