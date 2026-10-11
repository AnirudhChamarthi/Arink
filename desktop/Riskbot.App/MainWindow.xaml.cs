using System.Windows;
using System.Windows.Input;
using Riskbot.App.ViewModels;
using Riskbot.App.Views;

namespace Riskbot.App;

public partial class MainWindow : Window
{
    public MainWindow(MainViewModel viewModel)
    {
        InitializeComponent();
        DataContext = viewModel;
        Blotter.DataContext = viewModel.Blotter;
        Treemap.DataContext = viewModel.Treemap;
        NlqBar.DataContext = viewModel.Nlq;
        Results.DataContext = viewModel.Result;

        InputBindings.Add(new KeyBinding(viewModel.NewPortfolioCommand, Key.N, ModifierKeys.Control));
        InputBindings.Add(new KeyBinding(viewModel.OpenPortfolioCommand, Key.O, ModifierKeys.Control));
        InputBindings.Add(new KeyBinding(viewModel.SaveCommand, Key.S, ModifierKeys.Control));
    }
}
