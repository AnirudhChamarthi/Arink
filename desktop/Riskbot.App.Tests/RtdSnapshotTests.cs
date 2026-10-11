using Riskbot.RtdBridge;

namespace Riskbot.App.Tests;

public class RtdSnapshotTests
{
    [Fact]
    public void TopicKey_is_case_insensitive_storage()
    {
        var snap = new RtdSnapshot();
        snap.SetValue("aapl", RtdFields.CurrentPrice, 150.0);
        Assert.True(snap.TryGetValue("AAPL", RtdFields.CurrentPrice, out var v));
        Assert.Equal(150.0, v);
    }

    [Fact]
    public void Snapshot_file_roundtrip()
    {
        Directory.CreateDirectory(RtdSnapshotPath.RiskbotDataRoot);
        var path = Path.Combine(RtdSnapshotPath.RiskbotDataRoot, $"riskbot_rtd_{Guid.NewGuid():N}.json");
        try
        {
            var original = new RtdSnapshot
            {
                PortfolioName = "Test",
            };
            original.SetValue("MSFT", RtdFields.PnL, 1234.5);

            RtdSnapshotFile.Write(path, original);
            var loaded = RtdSnapshotFile.TryRead(path);

            Assert.NotNull(loaded);
            Assert.Equal("Test", loaded!.PortfolioName);
            Assert.True(loaded.TryGetValue("MSFT", RtdFields.PnL, out var pnl));
            Assert.Equal(1234.5, pnl);
        }
        finally
        {
            if (File.Exists(path))
                File.Delete(path);
            var tmp = path + ".tmp";
            if (File.Exists(tmp))
                File.Delete(tmp);
        }
    }

    [Fact]
    public void ProgId_matches_excel_formula()
    {
        Assert.Equal("Riskbot.RTD", RtdSnapshot.ProgId);
    }
}
