using System.Text.RegularExpressions;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

public static class EsgPreferencesValidator
{
    public const int MaxFileBytes = 256 * 1024;
    public const int MaxListItems = 100;
    public const int MaxTickerLength = 20;
    public const int MaxKeywordLength = 64;
    public const int MaxMergedExclusionTokens = 500;

    private static readonly Regex TickerPattern = new(
        @"^[A-Za-z][A-Za-z0-9.\-]{0,19}$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static EsgPreferences Sanitize(EsgPreferences? source)
    {
        source ??= EsgPreferencesStore.Default();
        return new EsgPreferences
        {
            EnabledPresets = source.EnabledPresets
                .Where(p => ExclusionPolicy.PresetIds.Contains(p, StringComparer.OrdinalIgnoreCase))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(MaxListItems)
                .ToList(),
            ExcludedTickers = source.ExcludedTickers
                .Select(NormalizeTicker)
                .Where(t => t is not null)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(MaxListItems)
                .Cast<string>()
                .ToList(),
            ExcludedNameKeywords = source.ExcludedNameKeywords
                .Select(NormalizeKeyword)
                .Where(k => k is not null)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(MaxListItems)
                .Cast<string>()
                .ToList(),
            CustomSectorKeywords = source.CustomSectorKeywords
                .Select(NormalizeKeyword)
                .Where(k => k is not null)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(MaxListItems)
                .Cast<string>()
                .ToList(),
            EsgMinScore = source.EsgMinScore is >= 0 and <= 100 ? source.EsgMinScore : null,
        };
    }

    public static string? NormalizeTicker(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;
        var t = value.Trim().ToUpperInvariant();
        return TickerPattern.IsMatch(t) ? t : null;
    }

    public static string? NormalizeKeyword(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;
        var k = value.Trim().ToLowerInvariant();
        if (k.Length > MaxKeywordLength)
            k = k[..MaxKeywordLength];
        if (k.Any(c => c is '=' or '+' or '-' or '@' or '\t' or '\r' or '\n'))
            return null;
        return k.Length > 0 ? k : null;
    }
}
