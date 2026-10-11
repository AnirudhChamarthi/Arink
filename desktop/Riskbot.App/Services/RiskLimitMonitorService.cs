using Riskbot.App.ApiClient;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

/// <summary>Runs limit checks on enrichment and VaR events; publishes breach updates.</summary>
public sealed class RiskLimitMonitorService
{
    private readonly MessageBus _bus;
    private readonly PortfolioWorkspaceService _workspace;
    private readonly EsgPreferencesService _esgPrefs;
    private readonly List<BlotterRow> _rows = [];
    private RiskLimitsDto _limits = new();
    private long _generation;
    private double? _portfolioVar;
    private double? _portfolioEsg;

    public RiskLimitMonitorService(
        MessageBus bus,
        PortfolioWorkspaceService workspace,
        EsgPreferencesService esgPrefs)
    {
        _bus = bus;
        _workspace = workspace;
        _esgPrefs = esgPrefs;
        _esgPrefs.PreferencesChanged += OnPreferencesChanged;
        _bus.Subscribe<PortfolioLoadedEvent>(_ => { Reset(); return Task.CompletedTask; });
        _bus.Subscribe<EnrichmentStartedEvent>(e =>
        {
            _generation = e.EnrichGeneration;
            _portfolioVar = null;
            _portfolioEsg = null;
            SetLimitsFromWorkspace();
            return Task.CompletedTask;
        });
        _bus.Subscribe<VarLoadedEvent>(OnVarLoadedAsync);
    }

    private Task OnVarLoadedAsync(VarLoadedEvent evt)
    {
        if (evt.EnrichGeneration != _generation)
            return Task.CompletedTask;

        _portfolioVar = evt.PortfolioVar;
        return PublishBreachesAsync(evt.EnrichGeneration);
    }

    public void SyncRows(IReadOnlyList<BlotterRow> rows)
    {
        _rows.Clear();
        _rows.AddRange(rows);
    }

    public void SetLimitsFromWorkspace() =>
        ApplyLimits(RiskLimitsResolver.Resolve(_workspace.Current?.Metadata, _esgPrefs.Current));

    /// <summary>Apply resolved limits (also used after preference changes and in tests).</summary>
    public void ApplyLimits(RiskLimitsDto limits) => _limits = limits;

    private void OnPreferencesChanged()
    {
        SetLimitsFromWorkspace();
        if (_generation > 0 && _rows.Count > 0)
            _ = RefreshAsync(_generation);
    }

    private void Reset()
    {
        _rows.Clear();
        _limits = new RiskLimitsDto();
        _generation = 0;
        _portfolioVar = null;
        _portfolioEsg = null;
    }

    public Task RefreshAsync(long generation) => PublishBreachesAsync(generation);

    private Task PublishBreachesAsync(long generation)
    {
        if (_rows.Count == 0)
            return Task.CompletedTask;

        _portfolioEsg = RiskLimitMonitor.WeightedPortfolioEsg(_rows);
        var evaluation = RiskLimitMonitor.Evaluate(_rows, _limits, _portfolioVar, _portfolioEsg);

        return _bus.PublishAsync(new RiskBreachesUpdatedEvent
        {
            EnrichGeneration = generation,
            PositionBreaches = evaluation.PositionBreaches,
            PortfolioBreaches = evaluation.PortfolioBreaches,
        });
    }
}
