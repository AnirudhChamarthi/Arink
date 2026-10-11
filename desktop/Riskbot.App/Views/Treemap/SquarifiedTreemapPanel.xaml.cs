using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using Riskbot.App.Models;
using Riskbot.App.ViewModels;

namespace Riskbot.App.Views.Treemap;

public partial class SquarifiedTreemapPanel : UserControl
{
    private TreemapViewModel? _viewModel;
    private readonly Dictionary<string, FrameworkElement> _elementsByTicker = new(StringComparer.OrdinalIgnoreCase);

    public SquarifiedTreemapPanel()
    {
        InitializeComponent();
        DataContextChanged += (_, _) => AttachViewModel();
        Loaded += (_, _) => Redraw();
    }

    private void AttachViewModel()
    {
        if (_viewModel is not null)
            _viewModel.PropertyChanged -= OnViewModelPropertyChanged;

        _viewModel = DataContext as TreemapViewModel;
        if (_viewModel is not null)
            _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        Redraw();
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(TreemapViewModel.LayoutTick)
            or nameof(TreemapViewModel.HasTiles)
            or nameof(TreemapViewModel.Mode))
            Redraw();
    }

    private void OnSizeChanged(object sender, SizeChangedEventArgs e) => Redraw();

    private void Redraw()
    {
        try
        {
            ChartCanvas.Children.Clear();
            _elementsByTicker.Clear();

            if (_viewModel is null || !_viewModel.HasTiles)
                return;

            var w = ActualWidth;
            var h = ActualHeight;
            if (double.IsNaN(w) || double.IsNaN(h) || w < 4 || h < 4)
                return;

            _viewModel.UpdateLayout(w, h);
            foreach (var rect in _viewModel.LayoutRects)
                AddTile(rect);
        }
        catch
        {
            // Panel not sized yet or layout edge case — skip this frame.
        }
    }

    private void AddTile(TreemapLayoutRect layout)
    {
        var tile = layout.Tile;
        var bounds = layout.Bounds;
        var w = Math.Max(0, bounds.Width);
        var h = Math.Max(0, bounds.Height);
        if (w < 1 || h < 1)
            return;

        var border = new Border
        {
            Width = w,
            Height = h,
            Background = new SolidColorBrush(tile.FillColor),
            BorderBrush = tile.IsSelected
                ? new SolidColorBrush(Color.FromRgb(0xFF, 0xD5, 0x4F))
                : new SolidColorBrush(Color.FromArgb(0x40, 0, 0, 0)),
            BorderThickness = tile.IsSelected
                ? new Thickness(3)
                : new Thickness(1),
            ToolTip = tile.Tooltip,
            Cursor = Cursors.Hand,
            Tag = tile,
        };

        if (bounds.Width > 48 && bounds.Height > 22)
        {
            border.Child = new TextBlock
            {
                Text = tile.Ticker,
                Foreground = Brushes.White,
                FontSize = Math.Min(14, bounds.Height * 0.35),
                FontWeight = FontWeights.SemiBold,
                Margin = new Thickness(4, 2, 2, 2),
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
        }

        border.MouseLeftButtonDown += OnTileClick;
        Canvas.SetLeft(border, bounds.X);
        Canvas.SetTop(border, bounds.Y);
        ChartCanvas.Children.Add(border);
        _elementsByTicker[tile.Ticker] = border;
    }

    private void OnTileClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is FrameworkElement el && el.Tag is TreemapTile tile)
            _viewModel?.SelectTile(tile);
        e.Handled = true;
    }
}
