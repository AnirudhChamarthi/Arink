namespace Riskbot.RtdBridge;

/// <summary>Bounds for RTD snapshot files and Excel topic strings.</summary>
public static class RtdSnapshotLimits
{
    public const int MaxSnapshotBytes = 5 * 1024 * 1024;
    public const int MaxTopicEntries = 50_000;
    public const int MaxTickerLength = 32;
    public const int MaxFieldLength = 64;
    public const int MaxExcelSubscriptions = 10_000;
}
