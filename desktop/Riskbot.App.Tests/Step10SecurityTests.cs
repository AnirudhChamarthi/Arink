using Riskbot.App.Helpers;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class Step10SecurityTests
{
    [Fact]
    public void Sanitize_rejects_invalid_tickers_and_caps_lists()
    {
        var raw = new EsgPreferences
        {
            EnabledPresets = ["weapons", "not_a_real_preset"],
            ExcludedTickers = ["PLTR", "../../../etc", new string('X', 50)],
            ExcludedNameKeywords = ["palantir", "=cmd"],
            CustomSectorKeywords = ["surveillance"],
            EsgMinScore = 150,
        };

        var clean = EsgPreferencesValidator.Sanitize(raw);

        Assert.Single(clean.EnabledPresets);
        Assert.Equal("weapons", clean.EnabledPresets[0]);
        Assert.Single(clean.ExcludedTickers);
        Assert.Equal("PLTR", clean.ExcludedTickers[0]);
        Assert.Single(clean.ExcludedNameKeywords);
        Assert.Equal("palantir", clean.ExcludedNameKeywords[0]);
        Assert.Null(clean.EsgMinScore);
    }

    [Fact]
    public void Preferences_store_rejects_oversized_file()
    {
        var path = Path.Combine(Path.GetTempPath(), $"riskbot_esg_{Guid.NewGuid():N}.json");
        try
        {
            File.WriteAllText(path, new string('x', EsgPreferencesValidator.MaxFileBytes + 1));
            var store = new TestEsgPreferencesStore(path);
            var loaded = store.Load();
            Assert.Empty(loaded.ExcludedTickers);
        }
        finally
        {
            if (File.Exists(path))
                File.Delete(path);
        }
    }

    [Fact]
    public void RiskLimitsResolver_caps_merged_exclusion_token_count()
    {
        var prefs = new EsgPreferences
        {
            ExcludedTickers = Enumerable.Range(0, 600).Select(i => $"T{i:D3}").ToList(),
        };
        prefs = EsgPreferencesValidator.Sanitize(prefs);

        var dto = RiskLimitsResolver.Resolve(null, prefs);
        Assert.True(dto.ExclusionFilters.Count <= EsgPreferencesValidator.MaxMergedExclusionTokens);
    }

    [Fact]
    public void Portfolio_esg_breach_detected()
    {
        var rows = new List<BlotterRow>
        {
            new() { Ticker = "A", WeightPercent = 50, MarketValue = 50, EsgScore = 30 },
            new() { Ticker = "B", WeightPercent = 50, MarketValue = 50, EsgScore = 30 },
        };
        var limits = new ApiClient.RiskLimitsDto { EsgMinScore = 40 };
        var result = RiskLimitMonitor.Evaluate(rows, limits, null, portfolioEsgScore: 30);

        Assert.Contains(RiskLimitMonitor.PortfolioEsg, result.PortfolioBreaches);
    }

    private sealed class TestEsgPreferencesStore(string path)
    {
        public EsgPreferences Load()
        {
            if (!File.Exists(path))
                return EsgPreferencesStore.Default();
            var info = new FileInfo(path);
            if (info.Length > EsgPreferencesValidator.MaxFileBytes)
                return EsgPreferencesStore.Default();
            var json = File.ReadAllText(path);
            var raw = System.Text.Json.JsonSerializer.Deserialize<EsgPreferences>(json);
            return EsgPreferencesValidator.Sanitize(raw);
        }
    }
}
