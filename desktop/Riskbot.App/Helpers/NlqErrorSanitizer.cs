using System.Net.Http;

namespace Riskbot.App.Helpers;

public static class NlqErrorSanitizer
{
    public const int MaxQueryLength = 4000;

    private const string GenericFailure =
        "The risk engine could not complete your query. Try refreshing market data or rephrasing your question.";

    public static string ForUser(Exception ex)
    {
        if (ex is HttpRequestException http)
            return ForHttpFailure(http);

        return ex switch
        {
            InvalidOperationException ioe when !string.IsNullOrWhiteSpace(ioe.Message) => ioe.Message,
            _ => GenericFailure,
        };
    }

    private static string ForHttpFailure(HttpRequestException http)
    {
        var message = http.Message;
        if (message.Contains("(422)", StringComparison.Ordinal))
            return ExtractDetail(message) ?? "The query or portfolio session was invalid.";

        if (message.Contains("(502)", StringComparison.Ordinal)
            || message.Contains("(500)", StringComparison.Ordinal))
            return GenericFailure;

        return GenericFailure;
    }

    private static string? ExtractDetail(string message)
    {
        var marker = "): ";
        var idx = message.IndexOf(marker, StringComparison.Ordinal);
        if (idx < 0)
            return null;
        var detail = message[(idx + marker.Length)..].Trim();
        return detail.Length > 240 ? detail[..240] + "…" : detail;
    }
}
