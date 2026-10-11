using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

public sealed class EnrichmentService
{
    private readonly MessageBus _bus;
    private readonly RiskbotApiClient _api;
    private readonly PortfolioSessionState _session;
    private readonly EngineHostService _engine;
    private PortfolioFile? _pending;

    public EnrichmentService(
        MessageBus bus,
        RiskbotApiClient api,
        PortfolioSessionState session,
        EngineHostService engine)
    {
        _bus = bus;
        _api = api;
        _session = session;
        _engine = engine;
        _bus.Subscribe<PortfolioLoadedEvent>(OnPortfolioLoadedAsync);
    }

    public async Task RefreshAsync()
    {
        if (_pending is not null)
            await RunEnrichmentAsync(_pending).ConfigureAwait(false);
    }

    private Task OnPortfolioLoadedAsync(PortfolioLoadedEvent evt)
    {
        _pending = evt.Portfolio;
        return RunEnrichmentAsync(evt.Portfolio);
    }

    private async Task RunEnrichmentAsync(PortfolioFile portfolio)
    {
        var generation = _session.BeginEnrich();

        if (_engine.State != EngineConnectionState.Online)
        {
            await _engine.EnsureRunningAsync().ConfigureAwait(false);
            if (_engine.State != EngineConnectionState.Online)
            {
                await _bus.PublishAsync(new EnrichmentFailedEvent
                {
                    EnrichGeneration = generation,
                    Message = "Engine is offline.",
                }).ConfigureAwait(false);
                return;
            }
        }

        await _bus.PublishAsync(new EnrichmentStartedEvent
        {
            PortfolioName = portfolio.Metadata.PortfolioName,
            EnrichGeneration = generation,
        }).ConfigureAwait(false);

        var request = MapEnrichRequest(portfolio);
        EnrichResponseDto enrichResult;
        try
        {
            enrichResult = await _api.EnrichAsync(request).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            await _bus.PublishAsync(new EnrichmentFailedEvent
            {
                EnrichGeneration = generation,
                Message = ex.Message,
            }).ConfigureAwait(false);
            return;
        }

        if (_session.EnrichGeneration != generation)
            return;

        _session.SetEnrichResult(enrichResult);
        var total = enrichResult.Portfolio.Positions.Count;
        for (var i = 0; i < total; i++)
        {
            await _bus.PublishAsync(new EnrichmentCompleteEvent
            {
                Position = enrichResult.Portfolio.Positions[i],
                EnrichGeneration = generation,
                Index = i,
                Total = total,
            }).ConfigureAwait(false);
        }

        await _bus.PublishAsync(new EnrichmentFinishedEvent
        {
            PortfolioSessionId = enrichResult.PortfolioSessionId,
            EnrichGeneration = generation,
            PositionCount = total,
        }).ConfigureAwait(false);
    }

    private static EnrichRequest MapEnrichRequest(PortfolioFile portfolio) => new()
    {
        PortfolioName = portfolio.Metadata.PortfolioName,
        BaseCurrency = portfolio.Metadata.BaseCurrency,
        Benchmark = portfolio.Metadata.Benchmark,
        Positions = portfolio.Holdings.Select(h => new RawPositionDto
        {
            Ticker = h.Ticker,
            Isin = h.Isin,
            AssetClass = h.AssetClass,
            Quantity = h.Quantity,
            CostPrice = h.CostPrice,
            Currency = h.Currency,
            Sector = h.Sector,
            Country = h.Country,
            EsgOverride = h.EsgOverride,
        }).ToList(),
    };
}
