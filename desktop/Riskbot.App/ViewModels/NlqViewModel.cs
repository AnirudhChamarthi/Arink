using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;
using Riskbot.App.Services;

namespace Riskbot.App.ViewModels;

public sealed partial class NlqViewModel : ObservableObject
{
    private readonly NlqService _nlq;
    private readonly EngineHostService _engine;
    private readonly PortfolioSessionState _session;
    private readonly PortfolioWorkspaceService _workspace;
    private readonly ResultViewModel _results;
    private long _enrichGeneration;

    public NlqViewModel(
        NlqService nlq,
        EngineHostService engine,
        PortfolioSessionState session,
        PortfolioWorkspaceService workspace,
        ResultViewModel results,
        MessageBus bus)
    {
        _nlq = nlq;
        _engine = engine;
        _session = session;
        _workspace = workspace;
        _results = results;
        _engine.StatusChanged += RefreshAvailability;
        _workspace.PortfolioChanged += RefreshAvailability;
        bus.Subscribe<PortfolioLoadedEvent>(_ =>
        {
            OnPortfolioLoaded();
            return Task.CompletedTask;
        });
        bus.Subscribe<EnrichmentFinishedEvent>(OnEnrichmentFinishedAsync);
        bus.Subscribe<EnrichmentFailedEvent>(OnEnrichmentFailedAsync);
        RefreshAvailability();
    }

    [ObservableProperty]
    private string _queryText = "";

    [ObservableProperty]
    private bool _isEnabled;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _hintText = "Open a portfolio and wait for enrichment";

    public bool CanSend =>
        IsEnabled && !IsBusy
        && !string.IsNullOrWhiteSpace(QueryText)
        && QueryText.Length <= NlqErrorSanitizer.MaxQueryLength;

    partial void OnQueryTextChanged(string value) => OnPropertyChanged(nameof(CanSend));

    partial void OnIsEnabledChanged(bool value) => OnPropertyChanged(nameof(CanSend));

    partial void OnIsBusyChanged(bool value) => OnPropertyChanged(nameof(CanSend));

    [RelayCommand(CanExecute = nameof(CanSend))]
    private async Task SendQueryAsync()
    {
        if (_enrichGeneration <= 0)
            return;

        if (QueryText.Length > NlqErrorSanitizer.MaxQueryLength)
        {
            System.Windows.MessageBox.Show(
                $"Questions must be {NlqErrorSanitizer.MaxQueryLength} characters or fewer.",
                "Riskbot",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning);
            return;
        }

        IsBusy = true;
        OnPropertyChanged(nameof(CanSend));
        try
        {
            await _nlq.SubmitAsync(QueryText, _enrichGeneration).ConfigureAwait(true);
            QueryText = "";
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(NlqErrorSanitizer.ForUser(ex), "Riskbot",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning);
        }
        finally
        {
            IsBusy = false;
            OnPropertyChanged(nameof(CanSend));
        }
    }

    private void OnPortfolioLoaded()
    {
        App.Current.Dispatcher.Invoke(() =>
        {
            _enrichGeneration = 0;
            _results.SetActiveGeneration(0);
            HintText = "Enriching portfolio…";
            RefreshAvailability();
        });
    }

    private Task OnEnrichmentFinishedAsync(EnrichmentFinishedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _enrichGeneration = evt.EnrichGeneration;
            _results.SetActiveGeneration(evt.EnrichGeneration);
            HintText = "Type a risk question… e.g. What is my 99% 1-day VaR?";
            RefreshAvailability();
        }).Task;
    }

    private Task OnEnrichmentFailedAsync(EnrichmentFailedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _enrichGeneration && _enrichGeneration != 0)
                return;
            _enrichGeneration = 0;
            HintText = "Enrichment failed — fix portfolio or refresh market data";
            RefreshAvailability();
        }).Task;
    }

    private void RefreshAvailability()
    {
        App.Current.Dispatcher.Invoke(() =>
        {
            var online = _engine.State == EngineConnectionState.Online;
            var hasPortfolio = _workspace.Current is not null;
            var hasSession = !string.IsNullOrWhiteSpace(_session.PortfolioSessionId) && _enrichGeneration > 0;
            IsEnabled = online && hasPortfolio && hasSession && !IsBusy;
            if (!online)
                HintText = "Waiting for engine…";
            else if (!hasPortfolio)
                HintText = "Open a portfolio to ask questions";
            else if (!hasSession)
                HintText = HintText.Contains("failed") ? HintText : "Enriching portfolio…";
            OnPropertyChanged(nameof(CanSend));
        });
    }
}
