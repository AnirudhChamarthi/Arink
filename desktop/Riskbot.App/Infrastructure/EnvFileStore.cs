namespace Riskbot.App.Infrastructure;

/// <summary>
/// Read/write repo-root <c>.env</c>. Creates from <c>.env.example</c> when missing.
/// Secrets stay local — <c>.env</c> is gitignored and never committed.
/// </summary>
public sealed class EnvFileStore
{
    public const string AnthropicApiKeyName = "ANTHROPIC_API_KEY";

    private const string DefaultEnvTemplate = """
        # Riskbot local secrets (gitignored). See .env.example for descriptions.

        ANTHROPIC_API_KEY=

        """;

    public EnvFileStore(string? repoRoot = null)
    {
        RepoRoot = repoRoot ?? RepoPaths.FindRepoRoot();
    }

    public string? RepoRoot { get; }

    public string? EnvFilePath => RepoRoot is null ? null : Path.Combine(RepoRoot, ".env");

    public string? ExampleFilePath => RepoRoot is null ? null : Path.Combine(RepoRoot, ".env.example");

    public bool EnvFileExists => EnvFilePath is not null && File.Exists(EnvFilePath);

    /// <summary>Creates <c>.env</c> from <c>.env.example</c> or a minimal template. Returns false if repo root not found.</summary>
    public bool EnsureEnvFileExists(out bool created)
    {
        created = false;
        var path = EnvFilePath;
        if (path is null)
            return false;

        if (File.Exists(path))
            return true;

        var example = ExampleFilePath;
        if (example is not null && File.Exists(example))
            File.Copy(example, path);
        else
            File.WriteAllText(path, DefaultEnvTemplate);

        created = true;
        return true;
    }

    public string? GetValue(string key)
    {
        var path = EnvFilePath;
        if (path is null || !File.Exists(path))
            return null;

        foreach (var rawLine in File.ReadLines(path))
        {
            if (!TryParseAssignment(rawLine, out var parsedKey, out var value))
                continue;
            if (string.Equals(parsedKey, key, StringComparison.Ordinal))
                return value;
        }

        return null;
    }

    public void SetValue(string key, string? value)
    {
        if (EnvFilePath is null)
            throw new InvalidOperationException("Could not locate the project folder (.env path unknown).");

        EnsureEnvFileExists(out _);

        var lines = File.Exists(EnvFilePath!)
            ? File.ReadAllLines(EnvFilePath!).ToList()
            : [];

        var newLine = $"{key}={value ?? ""}";
        var replaced = false;
        for (var i = 0; i < lines.Count; i++)
        {
            if (TryParseAssignment(lines[i], out var parsedKey, out _) &&
                string.Equals(parsedKey, key, StringComparison.Ordinal))
            {
                lines[i] = newLine;
                replaced = true;
                break;
            }
        }

        if (!replaced)
            lines.Add(newLine);

        File.WriteAllLines(EnvFilePath!, lines);
    }

    public void ClearValue(string key) => SetValue(key, "");

    public void ApplyToProcessEnvironment(string key, string? value)
    {
        if (string.IsNullOrEmpty(value))
            Environment.SetEnvironmentVariable(key, null);
        else
            Environment.SetEnvironmentVariable(key, value);
    }

    internal static bool TryParseAssignment(string rawLine, out string key, out string? value)
    {
        key = "";
        value = null;
        var line = rawLine.Trim();
        if (line.Length == 0 || line.StartsWith('#'))
            return false;

        var eq = line.IndexOf('=');
        if (eq <= 0)
            return false;

        key = line[..eq].Trim();
        if (key.Length == 0)
            return false;

        value = Unquote(line[(eq + 1)..].Trim());
        return true;
    }

    private static string Unquote(string text)
    {
        if (text.Length >= 2
            && ((text.StartsWith('"') && text.EndsWith('"'))
                || (text.StartsWith('\'') && text.EndsWith('\''))))
            return text[1..^1];
        return text;
    }
}
