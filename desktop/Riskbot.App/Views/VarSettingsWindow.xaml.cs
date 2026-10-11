using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using Riskbot.App.Services;

namespace Riskbot.App.Views;

public partial class VarSettingsWindow : Window
{
    private readonly VarSettingsService _settings;

    public VarSettingsWindow(VarSettingsService settings)
    {
        InitializeComponent();
        _settings = settings;
        MethodBox.SelectedItem = MethodBox.Items
            .Cast<ComboBoxItem>()
            .FirstOrDefault(i => (string)i.Content == _settings.Method)
            ?? MethodBox.Items[0];
        ConfidenceBox.Text = (_settings.Confidence * 100).ToString("F0", CultureInfo.InvariantCulture);
        HorizonBox.Text = _settings.HorizonDays.ToString(CultureInfo.InvariantCulture);
    }

    private void OnOk(object sender, RoutedEventArgs e)
    {
        var method = (MethodBox.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "parametric";
        if (!double.TryParse(ConfidenceBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var confPct)
            || confPct < 50 || confPct > 99.9)
        {
            MessageBox.Show("Confidence must be between 50 and 99.9.", "Riskbot");
            return;
        }

        if (!int.TryParse(HorizonBox.Text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var horizon)
            || horizon < 1 || horizon > 252)
        {
            MessageBox.Show("Horizon must be between 1 and 252 days.", "Riskbot");
            return;
        }

        _settings.Update(method, confPct / 100.0, horizon);
        DialogResult = true;
        Close();
    }
}
