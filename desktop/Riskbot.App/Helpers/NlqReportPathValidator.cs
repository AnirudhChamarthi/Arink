using Riskbot.App.Infrastructure;

namespace Riskbot.App.Helpers;

/// <summary>Ensures NLQ Excel paths stay under engine/output/reports before opening.</summary>
public static class NlqReportPathValidator
{
    public static bool TryValidate(string? path, out string? validatedPath)
    {
        validatedPath = null;
        if (string.IsNullOrWhiteSpace(path))
            return false;

        var engineDir = RepoPaths.FindEngineDirectory();
        if (engineDir is null)
            return false;

        var reportsRoot = Path.GetFullPath(Path.Combine(engineDir, "output", "reports"));
        string fullPath;
        try
        {
            fullPath = Path.GetFullPath(path);
        }
        catch
        {
            return false;
        }

        if (!IsUnderDirectory(fullPath, reportsRoot))
            return false;

        if (!File.Exists(fullPath))
            return false;

        if (!string.Equals(Path.GetExtension(fullPath), ".xlsx", StringComparison.OrdinalIgnoreCase))
            return false;

        validatedPath = fullPath;
        return true;
    }

    private static bool IsUnderDirectory(string filePath, string directoryPath)
    {
        var dir = directoryPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        return filePath.StartsWith(dir, StringComparison.OrdinalIgnoreCase)
               || string.Equals(filePath, directoryPath.TrimEnd(Path.DirectorySeparatorChar),
                   StringComparison.OrdinalIgnoreCase);
    }
}
