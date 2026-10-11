using Riskbot.App.Infrastructure;

namespace Riskbot.App.Tests;

public class EnvFileStoreTests
{
    [Fact]
    public void EnsureEnvFileExists_creates_from_example()
    {
        var root = Path.Combine(Path.GetTempPath(), $"riskbot_env_{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, ".env.example"), "ANTHROPIC_API_KEY=\n");

        try
        {
            var store = new EnvFileStore(root);
            Assert.True(store.EnsureEnvFileExists(out var created));
            Assert.True(created);
            Assert.True(File.Exists(store.EnvFilePath));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void SetValue_updates_and_reads_key()
    {
        var root = Path.Combine(Path.GetTempPath(), $"riskbot_env_{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);

        try
        {
            var store = new EnvFileStore(root);
            store.EnsureEnvFileExists(out _);
            store.SetValue(EnvFileStore.AnthropicApiKeyName, "sk-test-key");
            Assert.Equal("sk-test-key", store.GetValue(EnvFileStore.AnthropicApiKeyName));

            store.ClearValue(EnvFileStore.AnthropicApiKeyName);
            Assert.Equal("", store.GetValue(EnvFileStore.AnthropicApiKeyName));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
