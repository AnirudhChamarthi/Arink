using Microsoft.Win32;
using Riskbot.App.Bus;
using Riskbot.App.Bus.Events;
using Riskbot.App.ExcelIntegration;
using Riskbot.App.Models;

namespace Riskbot.App.Services;

public sealed class PortfolioWorkspaceService
{
    private readonly PortfolioFileManager _files;
    private readonly TemplateWriter _templates;
    private readonly MessageBus _bus;
    private readonly RecentFilesStore _recent;

    public PortfolioWorkspaceService(
        PortfolioFileManager files,
        TemplateWriter templates,
        MessageBus bus,
        RecentFilesStore recent)
    {
        _files = files;
        _templates = templates;
        _bus = bus;
        _recent = recent;
    }

    public PortfolioFile? Current { get; private set; }
    public bool IsDirty { get; private set; }

    public event Action? PortfolioChanged;

    public async Task NewPortfolioAsync()
    {
        var dlg = new SaveFileDialog
        {
            Title = "Create New Portfolio",
            Filter = "Excel portfolio (*.xlsx)|*.xlsx",
            FileName = "Portfolio.xlsx",
        };
        if (dlg.ShowDialog() != true)
            return;

        _templates.WriteBlankTemplate(dlg.FileName);
        await LoadFileAsync(dlg.FileName).ConfigureAwait(true);
    }

    public async Task OpenPortfolioAsync()
    {
        var dlg = new OpenFileDialog
        {
            Title = "Open Portfolio",
            Filter = "Excel portfolio (*.xlsx)|*.xlsx",
        };
        if (dlg.ShowDialog() != true)
            return;
        await LoadFileAsync(dlg.FileName).ConfigureAwait(true);
    }

    public async Task OpenRecentAsync(string path) => await LoadFileAsync(path).ConfigureAwait(true);

    public async Task LoadFileAsync(string path)
    {
        PortfolioFile portfolio;
        try
        {
            portfolio = _files.Read(path);
        }
        catch (PortfolioValidationException ex)
        {
            throw new InvalidOperationException(ex.Message, ex);
        }
        catch (Exception ex) when (ex is not InvalidOperationException)
        {
            throw new InvalidOperationException($"Could not open portfolio: {ex.Message}", ex);
        }

        Current = portfolio;
        IsDirty = false;
        _recent.Add(path);
        await _bus.PublishAsync(new PortfolioLoadedEvent { Portfolio = portfolio }).ConfigureAwait(true);
        PortfolioChanged?.Invoke();
    }

    public void Save()
    {
        if (Current is null)
            return;
        _files.Save(Current);
        IsDirty = false;
        PortfolioChanged?.Invoke();
    }

    public void SaveAs()
    {
        if (Current is null)
            return;
        var dlg = new SaveFileDialog
        {
            Title = "Save Portfolio As",
            Filter = "Excel portfolio (*.xlsx)|*.xlsx",
            FileName = Path.GetFileName(Current.FilePath),
        };
        if (dlg.ShowDialog() != true)
            return;

        Current = new PortfolioFile
        {
            FilePath = dlg.FileName,
            Metadata = Current.Metadata,
            Holdings = Current.Holdings,
        };
        _files.Save(Current);
        _recent.Add(Current.FilePath);
        IsDirty = false;
        PortfolioChanged?.Invoke();
    }

    public IReadOnlyList<string> RecentFiles => _recent.Load();
}
