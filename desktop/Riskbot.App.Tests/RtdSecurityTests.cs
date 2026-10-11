using Riskbot.RtdBridge;

namespace Riskbot.App.Tests;

public class RtdSecurityTests
{
    [Fact]
    public void Rejects_snapshot_path_outside_local_appdata_riskbot()
    {
        var outside = Path.Combine(Path.GetTempPath(), $"riskbot_escape_{Guid.NewGuid():N}.json");
        Assert.Null(RtdSnapshotFile.TryRead(outside));
        Assert.False(RtdSnapshotPath.TryResolveUnderRiskbotRoot(outside, out _));
    }

    [Fact]
    public void Accepts_snapshot_path_under_riskbot_root()
    {
        var root = RtdSnapshotPath.RiskbotDataRoot;
        Directory.CreateDirectory(root);
        var file = Path.Combine(root, $"riskbot_rtd_sec_{Guid.NewGuid():N}.json");
        try
        {
            Assert.True(RtdSnapshotPath.TryResolveUnderRiskbotRoot(file, out var resolved));
            Assert.Equal(Path.GetFullPath(file), resolved);

            var snap = new RtdSnapshot { PortfolioName = "SecTest" };
            snap.SetValue("AAPL", RtdFields.CurrentPrice, 1.0);
            RtdSnapshotFile.Write(file, snap);
            Assert.NotNull(RtdSnapshotFile.TryRead(file));
        }
        finally
        {
            if (File.Exists(file))
                File.Delete(file);
            var tmp = file + ".tmp";
            if (File.Exists(tmp))
                File.Delete(tmp);
        }
    }

    [Fact]
    public void Rejects_oversized_snapshot_file()
    {
        var root = RtdSnapshotPath.RiskbotDataRoot;
        Directory.CreateDirectory(root);
        var file = Path.Combine(root, $"riskbot_rtd_big_{Guid.NewGuid():N}.json");
        try
        {
            var padding = new string('x', RtdSnapshotLimits.MaxSnapshotBytes + 1);
            File.WriteAllText(file, $"{{\"topics\":{{\"AAPL|CurrentPrice\":1}},\"junk\":\"{padding}\"}}");
            Assert.Null(RtdSnapshotFile.TryRead(file));
        }
        finally
        {
            if (File.Exists(file))
                File.Delete(file);
        }
    }

    [Fact]
    public void Rejects_malformed_json()
    {
        var root = RtdSnapshotPath.RiskbotDataRoot;
        Directory.CreateDirectory(root);
        var file = Path.Combine(root, $"riskbot_rtd_bad_{Guid.NewGuid():N}.json");
        try
        {
            File.WriteAllText(file, "{ not valid json");
            Assert.Null(RtdSnapshotFile.TryRead(file));
        }
        finally
        {
            if (File.Exists(file))
                File.Delete(file);
        }
    }

    [Theory]
    [InlineData("AAPL", "CurrentPrice", true)]
    [InlineData("aapl", "currentprice", true)]
    [InlineData("", "CurrentPrice", false)]
    [InlineData("AAPL", "", false)]
    [InlineData("AAPL", "NotARealField", false)]
    [InlineData("../../../etc/passwd", "CurrentPrice", false)]
    public void Topic_validator_enforces_allowlist_and_bounds(string ticker, string field, bool ok)
    {
        Assert.Equal(ok, RtdTopicValidator.TryNormalize(ticker, field, out var t, out var f));
        if (ok)
        {
            Assert.Equal(ticker.Trim().ToUpperInvariant(), t);
            Assert.Equal(field, f, ignoreCase: true);
        }
    }

    [Fact]
    public void Topic_validator_rejects_overlong_ticker()
    {
        var longTicker = new string('X', RtdSnapshotLimits.MaxTickerLength + 1);
        Assert.False(RtdTopicValidator.TryNormalize(longTicker, RtdFields.PnL, out _, out _));
    }

    [Fact]
    public void Write_rejects_path_outside_riskbot_root()
    {
        var outside = Path.Combine(Path.GetTempPath(), $"riskbot_write_{Guid.NewGuid():N}.json");
        Assert.Throws<InvalidOperationException>(() =>
            RtdSnapshotFile.Write(outside, new RtdSnapshot()));
    }
}
