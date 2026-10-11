using System.Collections.ObjectModel;
using System.Diagnostics;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.Helpers;

namespace Riskbot.App.ViewModels;

public sealed partial class ResultViewModel : ObservableObject
{
    private long _activeGeneration;

    public ResultViewModel(MessageBus bus)
    {
        _bus = bus;
        _bus.Subscribe<NlqStartedEvent>(OnNlqStartedAsync);
        _bus.Subscribe<NlqResultEvent>(OnNlqResultAsync);
        _bus.Subscribe<NlqFailedEvent>(OnNlqFailedAsync);
        _bus.Subscribe<NlqCancelledEvent>(OnNlqCancelledAsync);
        _bus.Subscribe<PortfolioLoadedEvent>(OnPortfolioLoadedAsync);
    }

    private readonly MessageBus _bus;

    [ObservableProperty]
    private bool _hasResult;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _toplineNumber = "—";

    [ObservableProperty]
    private string _toplineLabel = "Ask a risk question above";

    [ObservableProperty]
    private string _explanation = "";

    [ObservableProperty]
    private string _statusMessage = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanOpenExcelReport))]
    [NotifyCanExecuteChangedFor(nameof(OpenExcelReportCommand))]
    private string? _excelReportPath;

    [ObservableProperty]
    private bool _isFormulaExpanded;

    public bool CanOpenExcelReport =>
        NlqReportPathValidator.TryValidate(ExcelReportPath, out _);

    public ObservableCollection<string> FormulaLines { get; } = [];

    [RelayCommand(CanExecute = nameof(CanOpenExcelReport))]
    private void OpenExcelReport()
    {
        if (!NlqReportPathValidator.TryValidate(ExcelReportPath, out var safePath))
            return;

        Process.Start(new ProcessStartInfo(safePath!) { UseShellExecute = true });
    }

    [RelayCommand]
    private void ToggleFormula() => IsFormulaExpanded = !IsFormulaExpanded;

    private Task OnPortfolioLoadedAsync(PortfolioLoadedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            _activeGeneration = 0;
            ResetPlaceholder("Enriching portfolio…");
        }).Task;
    }

    private Task OnNlqStartedAsync(NlqStartedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;
            IsBusy = true;
            StatusMessage = $"Running: {evt.Query}";
            HasResult = false;
        }).Task;
    }

    private Task OnNlqResultAsync(NlqResultEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            var r = evt.Result;
            ToplineNumber = r.ToplineNumber;
            ToplineLabel = r.ToplineLabel;
            Explanation = r.Explanation;
            ExcelReportPath = NlqReportPathValidator.TryValidate(r.ExcelReportPath, out var safe)
                ? safe
                : null;
            FormulaLines.Clear();
            foreach (var line in r.FormulaBreakdown)
                FormulaLines.Add(line);

            HasResult = true;
            IsBusy = false;
            StatusMessage = string.Join(", ", r.ModelsUsed);
        }).Task;
    }

    private Task OnNlqFailedAsync(NlqFailedEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            IsBusy = false;
            HasResult = false;
            ResetPlaceholder("Query failed");
            StatusMessage = evt.Message;
            Explanation = evt.Message;
        }).Task;
    }

    private Task OnNlqCancelledAsync(NlqCancelledEvent evt)
    {
        return App.Current.Dispatcher.InvokeAsync(() =>
        {
            if (evt.EnrichGeneration != _activeGeneration)
                return;

            IsBusy = false;
            HasResult = false;
            StatusMessage = "";
            ToplineLabel = "Ask a risk question above";
        }).Task;
    }

    public void SetActiveGeneration(long generation)
    {
        _activeGeneration = generation;
        if (generation > 0)
            ResetPlaceholder("Ask a risk question above");
    }

    private void ResetPlaceholder(string label)
    {
        HasResult = false;
        IsBusy = false;
        ToplineNumber = "—";
        ToplineLabel = label;
        Explanation = "";
        ExcelReportPath = null;
        FormulaLines.Clear();
        StatusMessage = "";
    }
}
