namespace Riskbot.App.Services;

/// <summary>Delegates to <see cref="ExclusionPolicy"/> (aligned with engine exclusion_policy.py).</summary>
public static class ExclusionChecker
{
    public static IReadOnlyList<string> MatchingFilters(
        string ticker,
        string? companyName,
        string? sector,
        IEnumerable<string> filterTokens) =>
        ExclusionPolicy.MatchingFilters(ticker, companyName, sector, filterTokens);
}
