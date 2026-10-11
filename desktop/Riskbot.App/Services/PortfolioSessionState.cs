using Riskbot.App.ApiClient;

namespace Riskbot.App.Services;

/// <summary>
/// Desktop session: slim display portfolio + engine session id for quant endpoints.
/// Full enriched book (returns, options) lives only on the Python engine.
/// </summary>
public sealed class PortfolioSessionState
{
    public string? PortfolioSessionId { get; private set; }

    public EnrichedPortfolioDto? DisplayPortfolio { get; private set; }

    /// <summary>Increments on each enrich attempt; used to ignore stale async VaR results.</summary>
    public long EnrichGeneration { get; private set; }

    /// <summary>Call before a new enrich — clears prior session and bumps generation.</summary>
    public long BeginEnrich()
    {
        Clear();
        return ++EnrichGeneration;
    }

    public void SetEnrichResult(EnrichResponseDto response)
    {
        PortfolioSessionId = response.PortfolioSessionId;
        DisplayPortfolio = response.Portfolio;
    }

    public void Clear()
    {
        PortfolioSessionId = null;
        DisplayPortfolio = null;
    }

    public bool Matches(long enrichGeneration, string? portfolioSessionId) =>
        EnrichGeneration == enrichGeneration
        && !string.IsNullOrWhiteSpace(portfolioSessionId)
        && string.Equals(PortfolioSessionId, portfolioSessionId, StringComparison.Ordinal);
}
