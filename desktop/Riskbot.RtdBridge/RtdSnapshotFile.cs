using System.Text.Json;

namespace Riskbot.RtdBridge;

public static class RtdSnapshotFile
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        MaxDepth = 16,
    };

    public static string DefaultPath => RtdSnapshotPath.DefaultSnapshotPath;

    public static void Write(string path, RtdSnapshot snapshot)
    {
        if (!RtdSnapshotPath.TryResolveUnderRiskbotRoot(path, out var resolved))
            throw new InvalidOperationException("RTD snapshot path must be under the Riskbot app data folder.");

        var dir = Path.GetDirectoryName(resolved);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        snapshot.UpdatedUtc = DateTimeOffset.UtcNow;
        if (snapshot.Topics.Count > RtdSnapshotLimits.MaxTopicEntries)
            throw new InvalidOperationException($"RTD snapshot exceeds {RtdSnapshotLimits.MaxTopicEntries} topics.");

        var json = JsonSerializer.Serialize(snapshot, JsonOptions);
        var temp = resolved + ".tmp";
        File.WriteAllText(temp, json);
        if (File.Exists(resolved))
            File.Replace(temp, resolved, null);
        else
            File.Move(temp, resolved);
    }

    public static RtdSnapshot? TryRead(string? path = null)
    {
        if (!RtdSnapshotPath.TryResolveUnderRiskbotRoot(path, out var resolved))
            return null;

        if (!File.Exists(resolved))
            return null;

        try
        {
            var info = new FileInfo(resolved);
            if (info.Length > RtdSnapshotLimits.MaxSnapshotBytes)
                return null;

            var json = File.ReadAllText(resolved);
            var snapshot = JsonSerializer.Deserialize<RtdSnapshot>(json, JsonOptions);
            if (snapshot is null || snapshot.Topics.Count > RtdSnapshotLimits.MaxTopicEntries)
                return null;

            return snapshot;
        }
        catch
        {
            return null;
        }
    }
}
