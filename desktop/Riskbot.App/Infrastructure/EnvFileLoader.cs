namespace Riskbot.App.Infrastructure;

/// <summary>Loads KEY=VALUE pairs from the repo-root <c>.env</c> into the process environment.</summary>
public static class EnvFileLoader
{
    public static void LoadRepoEnv()
    {
        var store = new EnvFileStore();
        store.EnsureEnvFileExists(out _);
        var path = store.EnvFilePath;
        if (path is null || !File.Exists(path))
            return;

        foreach (var rawLine in File.ReadLines(path))
        {
            if (!EnvFileStore.TryParseAssignment(rawLine, out var key, out var value))
                continue;

            var existing = Environment.GetEnvironmentVariable(key);
            if (string.IsNullOrEmpty(existing)
                || (string.Equals(key, EnvFileStore.AnthropicApiKeyName, StringComparison.Ordinal)
                    && string.IsNullOrWhiteSpace(existing)))
                store.ApplyToProcessEnvironment(key, value);
        }
    }
}
