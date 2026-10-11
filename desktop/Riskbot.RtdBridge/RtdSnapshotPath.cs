namespace Riskbot.RtdBridge;

public static class RtdSnapshotPath
{
    public static string RiskbotDataRoot =>
        Path.GetFullPath(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Riskbot"));

    public static string DefaultSnapshotPath =>
        Path.Combine(RiskbotDataRoot, "rtd_snapshot.json");

    /// <summary>Snapshot files must live under %LocalAppData%\Riskbot.</summary>
    public static bool TryResolveUnderRiskbotRoot(string? path, out string fullPath)
    {
        path ??= DefaultSnapshotPath;
        try
        {
            fullPath = Path.GetFullPath(path);
        }
        catch
        {
            fullPath = "";
            return false;
        }

        var root = RiskbotDataRoot;
        var prefix = root.EndsWith(Path.DirectorySeparatorChar)
            ? root
            : root + Path.DirectorySeparatorChar;

        return fullPath.Equals(root, StringComparison.OrdinalIgnoreCase)
               || fullPath.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }
}
