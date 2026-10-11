namespace Riskbot.App.ViewModels;

public sealed class RecentFileItem
{
    public required string Path { get; init; }
    public string DisplayName => System.IO.Path.GetFileName(Path);
}
