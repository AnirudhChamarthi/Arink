namespace Riskbot.RtdBridge;

public static class RtdTopicValidator
{
    private static readonly HashSet<string> AllowedFields =
        new(RtdFields.All, StringComparer.OrdinalIgnoreCase);

    public static bool TryNormalize(string? ticker, string? field, out string normalizedTicker, out string normalizedField)
    {
        normalizedTicker = ticker?.Trim() ?? "";
        normalizedField = field?.Trim() ?? "";

        if (normalizedTicker.Length == 0
            || normalizedField.Length == 0
            || normalizedTicker.Length > RtdSnapshotLimits.MaxTickerLength
            || normalizedField.Length > RtdSnapshotLimits.MaxFieldLength)
        {
            return false;
        }

        if (!AllowedFields.Contains(normalizedField))
            return false;

        normalizedTicker = normalizedTicker.ToUpperInvariant();
        if (!IsValidTickerCharacters(normalizedTicker))
            return false;

        return true;
    }

    private static bool IsValidTickerCharacters(string ticker)
    {
        foreach (var c in ticker)
        {
            if (char.IsAsciiLetterOrDigit(c) || c is '.' or '-')
                continue;
            return false;
        }

        return true;
    }
}
