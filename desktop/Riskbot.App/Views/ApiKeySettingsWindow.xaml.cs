using System.Windows;
using Riskbot.App.ViewModels;

namespace Riskbot.App.Views;

public partial class ApiKeySettingsWindow : Window
{
    private ApiKeySettingsViewModel? _viewModel;

    public ApiKeySettingsWindow(ApiKeySettingsViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        DataContext = viewModel;
        viewModel.RequestClose += OnRequestClose;
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        _viewModel?.Load();
        if (_viewModel is not null)
            KeyBoxHidden.Password = _viewModel.ApiKey;
        UpdateKeyVisibility();
    }

    private void OnRequestClose(bool accepted)
    {
        DialogResult = accepted;
        Close();
    }

    private void OnCancelClick(object sender, RoutedEventArgs e) => OnRequestClose(false);

    private void OnPasswordChanged(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null || _viewModel.ShowKey)
            return;
        _viewModel.ApiKey = KeyBoxHidden.Password;
    }

    private void OnShowKeyChanged(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
            return;

        if (_viewModel.ShowKey)
            _viewModel.ApiKey = KeyBoxHidden.Password;
        else
            KeyBoxHidden.Password = _viewModel.ApiKey;

        UpdateKeyVisibility();
    }

    private void UpdateKeyVisibility()
    {
        var show = _viewModel?.ShowKey == true;
        KeyBoxHidden.Visibility = show ? Visibility.Collapsed : Visibility.Visible;
        KeyBoxVisible.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
    }
}
