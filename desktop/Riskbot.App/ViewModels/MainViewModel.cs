using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Extensions.DependencyInjection;
using Riskbot.App.Services;

namespace Riskbot.App.ViewModels;

public sealed partial class MainViewModel : ObservableObject
{
    private readonly PortfolioWorkspaceService _workspace;
    private readonly EngineHostService _engine;
    private readonly EnrichmentService _enrichment;
    private readonly RiskAnalysisService _riskAnalysis;
    private readonly VarSettingsService _varSettings;
    private readonly RtdFeedService _rtdFeed;
    private readonly EsgPreferencesService _esgPrefs;

    public MainViewModel(
        PortfolioWorkspaceService workspace,
        EngineHostService engine,
        EnrichmentService enrichment,
        RiskAnalysisService riskAnalysis,
        VarSettingsService varSettings,
        RtdFeedService rtdFeed,
        EsgPreferencesService esgPrefs,
        BlotterViewModel blotter,
        TreemapViewModel treemap,
        NlqViewModel nlq,
        ResultViewModel result)
    {
        _workspace = workspace;
        _engine = engine;
        _enrichment = enrichment;
        _riskAnalysis = riskAnalysis;
        _varSettings = varSettings;
        _rtdFeed = rtdFeed;
        _esgPrefs = esgPrefs;
        Blotter = blotter;
        Treemap = treemap;
        Nlq = nlq;
        Result = result;
        _workspace.PortfolioChanged += RefreshChrome;
        _engine.StatusChanged += OnEngineStatusChanged;
        RefreshChrome();
        RefreshRecentFiles();
        OnEngineStatusChanged();
        _ = StartEngineAsync();
    }

    public BlotterViewModel Blotter { get; }
    public TreemapViewModel Treemap { get; }
    public NlqViewModel Nlq { get; }
    public ResultViewModel Result { get; }

    public ObservableCollection<RecentFileItem> RecentFiles { get; } = [];

    [ObservableProperty]
    private string _windowTitle = "Riskbot";

    [ObservableProperty]
    private string _engineStatus = "Engine: starting…";

    [ObservableProperty]
    private bool _isEngineOnline;

    [ObservableProperty]
    private bool _isResultPanelVisible = true;

    [RelayCommand]
    private async Task NewPortfolioAsync()
    {
        await _workspace.NewPortfolioAsync();
        RefreshChrome();
        RefreshRecentFiles();
    }

    [RelayCommand]
    private async Task OpenPortfolioAsync()
    {
        try
        {
            await _workspace.OpenPortfolioAsync();
            RefreshChrome();
            RefreshRecentFiles();
        }
        catch (Exception ex)
        {
            ShowPortfolioError(ex);
        }
    }

    [RelayCommand]
    private async Task OpenRecentAsync(RecentFileItem? item)
    {
        if (item is null) return;
        try
        {
            await _workspace.OpenRecentAsync(item.Path);
            RefreshChrome();
            RefreshRecentFiles();
        }
        catch (Exception ex)
        {
            ShowPortfolioError(ex);
        }
    }

    private static void ShowPortfolioError(Exception ex)
    {
        System.Windows.MessageBox.Show(
            ex.Message,
            "Could not open portfolio",
            System.Windows.MessageBoxButton.OK,
            System.Windows.MessageBoxImage.Warning);
    }

    [RelayCommand]
    private void Save() => _workspace.Save();

    [RelayCommand]
    private void SaveAs()
    {
        _workspace.SaveAs();
        RefreshChrome();
        RefreshRecentFiles();
    }

    [RelayCommand]
    private void Exit() => System.Windows.Application.Current.Shutdown();

    [RelayCommand]
    private void ToggleResultPanel() => IsResultPanelVisible = !IsResultPanelVisible;

    [RelayCommand]
    private void ToggleTreemapMode()
    {
        if (Treemap.CycleModeCommand.CanExecute(null))
            Treemap.CycleModeCommand.Execute(null);
    }

    [RelayCommand]
    private async Task RefreshMarketDataAsync()
    {
        if (_workspace.Current is null)
        {
            System.Windows.MessageBox.Show("Open a portfolio first.", "Riskbot");
            return;
        }
        await _enrichment.RefreshAsync().ConfigureAwait(true);
    }

    [RelayCommand]
    private void ShowRtdFormulas()
    {
        var window = new Views.RtdFormulasWindow(_rtdFeed)
        {
            Owner = System.Windows.Application.Current.MainWindow,
        };
        window.ShowDialog();
    }

    [RelayCommand]
    private void OpenApiKeySettings()
    {
        var vm = App.Services.GetRequiredService<ApiKeySettingsViewModel>();
        var window = new Views.ApiKeySettingsWindow(vm)
        {
            Owner = System.Windows.Application.Current.MainWindow,
        };
        window.ShowDialog();
    }

    [RelayCommand]
    private void About()
    {
        var version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version;
        var verText = version is null ? "" : $"Version {version.Major}.{version.Minor}.{version.Build}\n\n";
        System.Windows.MessageBox.Show(
            verText +
            "Riskbot — AI-augmented portfolio risk desktop.\n\n" +
            "NLQ, Excel reports with charts, Excel RTD, Greeks, stress, GARCH, and sustainability.\n\n" +
            "Engine: local FastAPI on http://127.0.0.1:8765/",
            "About Riskbot",
            System.Windows.MessageBoxButton.OK,
            System.Windows.MessageBoxImage.Information);
    }

    [RelayCommand]
    private void OpenModelDocumentation()
    {
        var window = new Views.ModelDocumentationWindow
        {
            Owner = System.Windows.Application.Current.MainWindow,
        };
        window.ShowDialog();
    }

    [RelayCommand]
    private async Task RunStressTestAsync(string? scenario)
    {
        if (string.IsNullOrWhiteSpace(scenario))
            return;
        try
        {
            await _riskAnalysis.RunStressAsync(scenario).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(ex.Message, "Riskbot",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning);
        }
    }

    [RelayCommand]
    private async Task RunFullRiskReportAsync()
    {
        if (_workspace.Current is null)
        {
            System.Windows.MessageBox.Show("Open a portfolio first.", "Riskbot");
            return;
        }

        try
        {
            IsResultPanelVisible = true;
            await _riskAnalysis.RunFullReportAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(ex.Message, "Riskbot",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Warning);
        }
    }

    [RelayCommand]
    private void OpenVarSettings()
    {
        var window = new Views.VarSettingsWindow(_varSettings)
        {
            Owner = System.Windows.Application.Current.MainWindow,
        };
        window.ShowDialog();
    }

    [RelayCommand]
    private void OpenEsgPreferences()
    {
        var window = new Views.EsgPreferencesWindow(_esgPrefs)
        {
            Owner = System.Windows.Application.Current.MainWindow,
        };
        window.ShowDialog();
    }

    private async Task StartEngineAsync()
    {
        await _engine.EnsureRunningAsync().ConfigureAwait(true);
        OnEngineStatusChanged();
    }

    private void OnEngineStatusChanged()
    {
        EngineStatus = _engine.StatusMessage;
        IsEngineOnline = _engine.State == EngineConnectionState.Online;
    }

    private void RefreshChrome()
    {
        var path = _workspace.Current?.FilePath;
        var name = path is null ? "untitled" : Path.GetFileName(path);
        var dirty = _workspace.IsDirty ? " *" : "";
        WindowTitle = $"Riskbot — {name}{dirty}";
    }

    private void RefreshRecentFiles()
    {
        RecentFiles.Clear();
        foreach (var p in _workspace.RecentFiles)
            RecentFiles.Add(new RecentFileItem { Path = p });
    }
}
