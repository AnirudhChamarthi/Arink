using Riskbot.App.Models;

namespace Riskbot.App.Services;

/// <summary>
/// User-defined exclusions: optional sector presets, explicit tickers, name keywords, custom sectors.
/// Aligns with engine/models/exclusion_policy.py.
/// </summary>
public static class ExclusionPolicy
{
    public static readonly string[] PresetIds = ["weapons", "tobacco", "fossil_fuels", "gambling"];

    private static readonly Dictionary<string, string[]> PresetSectorKeywords =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["weapons"] = ["defense", "aerospace", "weapons", "military"],
            ["tobacco"] = ["tobacco"],
            ["fossil_fuels"] = ["energy", "oil", "gas", "coal", "petroleum"],
            ["gambling"] = ["casino", "gambling"],
        };

    public static IReadOnlyList<string> ToFilterTokens(EsgPreferences prefs)
    {
        var tokens = new List<string>();
        foreach (var preset in prefs.EnabledPresets)
            tokens.Add(preset);
        foreach (var ticker in prefs.ExcludedTickers)
            tokens.Add($"ticker:{ticker.Trim().ToUpperInvariant()}");
        foreach (var name in prefs.ExcludedNameKeywords)
            tokens.Add($"name:{name.Trim().ToLowerInvariant()}");
        foreach (var sector in prefs.CustomSectorKeywords)
            tokens.Add($"sector:{sector.Trim().ToLowerInvariant()}");
        return tokens;
    }

    public static IReadOnlyList<string> MatchingFilters(
        string ticker,
        string? companyName,
        string? sector,
        IEnumerable<string> filterTokens)
    {
        var hits = new List<string>();
        var tickerUpper = ticker.Trim().ToUpperInvariant();
        var nameLower = (companyName ?? "").ToLowerInvariant();
        var sectorLower = (sector ?? "").ToLowerInvariant();

        foreach (var raw in filterTokens)
        {
            var token = raw.Trim();
            if (token.Length == 0)
                continue;

            var lower = token.ToLowerInvariant();
            if (lower.StartsWith("ticker:", StringComparison.Ordinal))
            {
                var excluded = token["ticker:".Length..].Trim().ToUpperInvariant();
                if (tickerUpper == excluded)
                    hits.Add($"ticker:{excluded}");
                continue;
            }

            if (lower.StartsWith("name:", StringComparison.Ordinal))
            {
                var kw = token["name:".Length..].Trim().ToLowerInvariant();
                if (kw.Length > 0 && nameLower.Contains(kw, StringComparison.Ordinal))
                    hits.Add($"name:{kw}");
                continue;
            }

            if (lower.StartsWith("sector:", StringComparison.Ordinal))
            {
                foreach (var part in token["sector:".Length..].Split(',', StringSplitOptions.TrimEntries))
                {
                    var kw = part.ToLowerInvariant();
                    if (kw.Length > 0 && SectorContains(sectorLower, kw))
                        hits.Add($"sector:{kw}");
                }
                continue;
            }

            if (PresetSectorKeywords.TryGetValue(lower, out var presetKeywords))
            {
                if (presetKeywords.Any(k => sectorLower.Contains(k, StringComparison.Ordinal)))
                    hits.Add(lower);
                continue;
            }

            if (IsBareTicker(token) && tickerUpper == token.ToUpperInvariant())
            {
                hits.Add($"ticker:{tickerUpper}");
                continue;
            }

            if (SectorContains(sectorLower, lower.Replace(" ", "_")))
                hits.Add(lower);
        }

        return hits;
    }

    private static bool SectorContains(string sectorLower, string keyword) =>
        !string.IsNullOrEmpty(sectorLower)
        && (sectorLower.Contains(keyword.Replace("_", " "), StringComparison.Ordinal)
            || sectorLower.Contains(keyword, StringComparison.Ordinal));

    private static bool IsBareTicker(string token) =>
        token.Length is >= 1 and <= 20
        && token.All(c => char.IsAsciiLetterOrDigit(c) || c is '.' or '-')
        && token.Any(char.IsAsciiLetter);
}
