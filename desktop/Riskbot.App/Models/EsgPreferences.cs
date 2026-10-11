namespace Riskbot.App.Models;

/// <summary>User ESG / exclusion preferences (app-wide, merged with portfolio metadata).</summary>
public sealed class EsgPreferences
{
    public List<string> EnabledPresets { get; set; } = [];

    /// <summary>Explicit tickers to exclude, e.g. PLTR (not whole defense sector).</summary>
    public List<string> ExcludedTickers { get; set; } = [];

    /// <summary>Company name substrings, e.g. palantir.</summary>
    public List<string> ExcludedNameKeywords { get; set; } = [];

    /// <summary>Extra sector keywords beyond presets.</summary>
    public List<string> CustomSectorKeywords { get; set; } = [];

    public double? EsgMinScore { get; set; }
}
