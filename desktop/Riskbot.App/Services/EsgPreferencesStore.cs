using System.Text.Json;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

public sealed class EsgPreferencesStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        MaxDepth = 8,
    };

    public static string PreferencesPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Riskbot",
            "esg_preferences.json");

    public EsgPreferences Load()
    {
        try
        {
            if (!File.Exists(PreferencesPath))
                return Default();

            var info = new FileInfo(PreferencesPath);
            if (info.Length > EsgPreferencesValidator.MaxFileBytes)
                return Default();

            var json = File.ReadAllText(PreferencesPath);
            var raw = JsonSerializer.Deserialize<EsgPreferences>(json, JsonOptions);
            return EsgPreferencesValidator.Sanitize(raw);
        }
        catch
        {
            return Default();
        }
    }

    public void Save(EsgPreferences prefs)
    {
        var sanitized = EsgPreferencesValidator.Sanitize(prefs);
        var dir = Path.GetDirectoryName(PreferencesPath);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);
        var json = JsonSerializer.Serialize(sanitized, JsonOptions);
        File.WriteAllText(PreferencesPath, json);
    }

    public static EsgPreferences Default() => new()
    {
        EnabledPresets = [],
        ExcludedTickers = [],
        ExcludedNameKeywords = [],
        CustomSectorKeywords = [],
        EsgMinScore = null,
    };
}
