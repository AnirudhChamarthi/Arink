using System.Diagnostics;

namespace Riskbot.App.Infrastructure;

/// <summary>Builds environment variables for the spawned Python engine process.</summary>
public static class EngineEnvironment
{
    public static void ApplyTo(ProcessStartInfo startInfo, EnvFileStore? store = null)
    {
        foreach (System.Collections.DictionaryEntry entry in Environment.GetEnvironmentVariables())
        {
            if (entry.Key is string key && entry.Value is string value)
                startInfo.Environment[key] = value;
        }

        store ??= new EnvFileStore();
        var apiKey = store.GetValue(EnvFileStore.AnthropicApiKeyName);
        if (!string.IsNullOrWhiteSpace(apiKey))
            startInfo.Environment[EnvFileStore.AnthropicApiKeyName] = apiKey.Trim();
    }
}
