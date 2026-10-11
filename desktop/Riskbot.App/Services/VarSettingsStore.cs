using System.Globalization;
using System.Text.Json;

namespace Riskbot.App.Services;

/// <summary>Persists VaR method / confidence / horizon under %LocalAppData%\Riskbot.</summary>
public sealed class VarSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    };

    public static string SettingsPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Riskbot",
            "var_settings.json");

    public VarSettingsSnapshot Load()
    {
        try
        {
            if (!File.Exists(SettingsPath))
                return VarSettingsSnapshot.Default();

            var raw = JsonSerializer.Deserialize<VarSettingsSnapshot>(File.ReadAllText(SettingsPath), JsonOptions);
            return Sanitize(raw);
        }
        catch
        {
            return VarSettingsSnapshot.Default();
        }
    }

    public void Save(VarSettingsSnapshot snapshot)
    {
        var dir = Path.GetDirectoryName(SettingsPath)!;
        Directory.CreateDirectory(dir);
        File.WriteAllText(SettingsPath, JsonSerializer.Serialize(Sanitize(snapshot), JsonOptions));
    }

    public static VarSettingsSnapshot Sanitize(VarSettingsSnapshot? raw)
    {
        raw ??= VarSettingsSnapshot.Default();
        var method = raw.Method?.Trim().ToLowerInvariant() ?? "parametric";
        if (method is not ("parametric" or "historical" or "montecarlo"))
            method = "parametric";

        var confidence = raw.Confidence;
        if (confidence is < 0.5 or > 0.999)
            confidence = 0.99;

        var horizon = raw.HorizonDays;
        if (horizon is < 1 or > 252)
            horizon = 1;

        return new VarSettingsSnapshot
        {
            Method = method,
            Confidence = confidence,
            HorizonDays = horizon,
        };
    }
}

public sealed class VarSettingsSnapshot
{
    public string Method { get; set; } = "parametric";

    public double Confidence { get; set; } = 0.99;

    public int HorizonDays { get; set; } = 1;

    public static VarSettingsSnapshot Default() => new();
}
