using System.Diagnostics;
using Riskbot.App.Infrastructure;

namespace Riskbot.App.Tests;

public class EngineEnvironmentTests
{
    [Fact]
    public void ApplyTo_sets_anthropic_key_from_env_file()
    {
        var root = Path.Combine(Path.GetTempPath(), $"riskbot_eng_{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, ".env"), "ANTHROPIC_API_KEY=sk-from-dotenv\n");

        try
        {
            var store = new EnvFileStore(root);
            var startInfo = new ProcessStartInfo { FileName = "python" };
            EngineEnvironment.ApplyTo(startInfo, store);

            Assert.True(startInfo.Environment.ContainsKey(EnvFileStore.AnthropicApiKeyName));
            Assert.Equal("sk-from-dotenv", startInfo.Environment[EnvFileStore.AnthropicApiKeyName]);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
