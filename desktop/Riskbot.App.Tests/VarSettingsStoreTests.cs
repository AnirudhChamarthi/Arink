using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class VarSettingsStoreTests
{
    [Fact]
    public void Save_and_load_round_trip()
    {
        try
        {
            var store = new VarSettingsStore();
            store.Save(new VarSettingsSnapshot
            {
                Method = "historical",
                Confidence = 0.95,
                HorizonDays = 5,
            });

            var loaded = store.Load();
            Assert.Equal("historical", loaded.Method);
            Assert.Equal(0.95, loaded.Confidence);
            Assert.Equal(5, loaded.HorizonDays);
        }
        finally
        {
            if (File.Exists(VarSettingsStore.SettingsPath))
                File.Delete(VarSettingsStore.SettingsPath);
        }
    }

    [Fact]
    public void Sanitize_rejects_invalid_values()
    {
        var clean = VarSettingsStore.Sanitize(new VarSettingsSnapshot
        {
            Method = "invalid",
            Confidence = 2.0,
            HorizonDays = 999,
        });

        Assert.Equal("parametric", clean.Method);
        Assert.Equal(0.99, clean.Confidence);
        Assert.Equal(1, clean.HorizonDays);
    }
}
