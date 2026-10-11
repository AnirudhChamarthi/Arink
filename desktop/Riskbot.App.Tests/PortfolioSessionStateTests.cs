using Riskbot.App.ApiClient;
using Riskbot.App.Services;

namespace Riskbot.App.Tests;

public class PortfolioSessionStateTests
{
    [Fact]
    public void BeginEnrich_clears_session_and_increments_generation()
    {
        var state = new PortfolioSessionState();
        state.SetEnrichResult(new EnrichResponseDto
        {
            PortfolioSessionId = "abc",
            Portfolio = new EnrichedPortfolioDto(),
        });

        var gen = state.BeginEnrich();

        Assert.Equal(1, gen);
        Assert.Null(state.PortfolioSessionId);
        Assert.Null(state.DisplayPortfolio);
        Assert.Equal(1, state.EnrichGeneration);
    }

    [Fact]
    public void Matches_requires_generation_and_session_id()
    {
        var state = new PortfolioSessionState();
        var gen = state.BeginEnrich();
        state.SetEnrichResult(new EnrichResponseDto
        {
            PortfolioSessionId = "session-1",
            Portfolio = new EnrichedPortfolioDto(),
        });

        Assert.True(state.Matches(gen, "session-1"));
        Assert.False(state.Matches(gen + 1, "session-1"));
        Assert.False(state.Matches(gen, "session-2"));
    }
}
