namespace Riskbot.App.Infrastructure;

public static class RepoPaths
{
    public static string? FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var engineMain = Path.Combine(dir.FullName, "engine", "main.py");
            var openapi = Path.Combine(dir.FullName, "shared", "openapi.yaml");
            if (File.Exists(engineMain) && File.Exists(openapi))
                return dir.FullName;
            dir = dir.Parent;
        }
        return null;
    }

    public static string? FindPortfolioSchemaPath()
    {
        var root = FindRepoRoot();
        if (root is null)
            return null;
        var candidate = Path.Combine(root, "shared", "portfolio_schema.json");
        return File.Exists(candidate) ? candidate : null;
    }

    public static string? FindEngineDirectory()
    {
        var root = FindRepoRoot();
        if (root is null)
            return null;
        var mainPy = Path.Combine(root, "engine", "main.py");
        return File.Exists(mainPy) ? Path.Combine(root, "engine") : null;
    }
}
