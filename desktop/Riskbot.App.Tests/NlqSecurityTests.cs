using Riskbot.App.Helpers;
using Riskbot.App.Infrastructure;

namespace Riskbot.App.Tests;

public class NlqReportPathValidatorTests
{
    [Fact]
    public void Rejects_path_outside_reports_directory()
    {
        Assert.False(NlqReportPathValidator.TryValidate(@"C:\Windows\System32\cmd.exe", out _));
    }

    [Fact]
    public void Accepts_xlsx_under_engine_output_reports()
    {
        var engineDir = RepoPaths.FindEngineDirectory();
        if (engineDir is null)
            return;

        var reportsDir = Path.Combine(engineDir, "output", "reports");
        Directory.CreateDirectory(reportsDir);
        var file = Path.Combine(reportsDir, $"riskbot_test_{Guid.NewGuid():N}.xlsx");
        File.WriteAllBytes(file, []);
        try
        {
            Assert.True(NlqReportPathValidator.TryValidate(file, out var safe));
            Assert.Equal(Path.GetFullPath(file), safe);
        }
        finally
        {
            File.Delete(file);
        }
    }
}

public class NlqErrorSanitizerTests
{
    [Fact]
    public void Hides_502_response_body()
    {
        var ex = new HttpRequestException("POST /nlq failed (502): internal stack trace here");
        var message = NlqErrorSanitizer.ForUser(ex);
        Assert.DoesNotContain("stack trace", message);
        Assert.Contains("could not complete", message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void MaxQueryLength_matches_engine()
    {
        Assert.Equal(4000, NlqErrorSanitizer.MaxQueryLength);
    }
}
