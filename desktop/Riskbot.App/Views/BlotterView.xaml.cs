using System.Windows.Controls;
using Riskbot.App.Models;
using Riskbot.App.ViewModels;

namespace Riskbot.App.Views;

public partial class BlotterView : UserControl
{
    private BlotterViewModel? _viewModel;
    private bool _syncingSelection;

    public BlotterView()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        DataContextChanged += (_, _) => AttachViewModel();
    }

    private void OnLoaded(object sender, System.Windows.RoutedEventArgs e)
    {
        AttachViewModel();
        BlotterGrid.SelectionChanged += OnGridSelectionChanged;
    }

    private void AttachViewModel()
    {
        if (_viewModel is not null)
            _viewModel.HighlightTickerRequested -= OnHighlightTickerRequested;

        _viewModel = DataContext as BlotterViewModel;
        if (_viewModel is not null)
            _viewModel.HighlightTickerRequested += OnHighlightTickerRequested;
    }

    private void OnGridSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_syncingSelection || _viewModel is null)
            return;
        if (BlotterGrid.SelectedItem is BlotterRow row)
            _viewModel.SelectRow(row);
        else
            _viewModel.ClearSelection();
    }

    private void OnHighlightTickerRequested(string? ticker)
    {
        if (_viewModel is null || string.IsNullOrEmpty(ticker))
            return;

        var row = _viewModel.Rows.FirstOrDefault(r =>
            string.Equals(r.Ticker, ticker, StringComparison.OrdinalIgnoreCase));
        if (row is null)
            return;

        try
        {
            _syncingSelection = true;
            BlotterGrid.SelectedItem = row;
            BlotterGrid.ScrollIntoView(row);
        }
        finally
        {
            _syncingSelection = false;
        }
    }
}
