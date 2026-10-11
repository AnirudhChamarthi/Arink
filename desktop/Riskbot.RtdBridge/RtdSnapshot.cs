namespace Riskbot.RtdBridge;

public sealed class RtdSnapshot
{
    public const string ProgId = "Riskbot.RTD";

    public DateTimeOffset UpdatedUtc { get; set; }

    public string PortfolioName { get; set; } = "";

    /// <summary>Flat topic keys: "AAPL|CurrentPrice" → value.</summary>
    public Dictionary<string, double> Topics { get; set; } =
        new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);

    public static string TopicKey(string ticker, string field) =>
        $"{ticker.Trim().ToUpperInvariant()}|{field}";

    public bool TryGetValue(string ticker, string field, out double value)
    {
        return Topics.TryGetValue(TopicKey(ticker, field), out value);
    }

    public void SetValue(string ticker, string field, double value) =>
        Topics[TopicKey(ticker, field)] = value;
}
