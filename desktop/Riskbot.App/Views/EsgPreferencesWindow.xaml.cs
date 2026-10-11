using System.Windows;
using Riskbot.App.Models;
using Riskbot.App.Services;

namespace Riskbot.App.Views;

public partial class EsgPreferencesWindow : Window
{
    private readonly EsgPreferencesService _prefs;

    public EsgPreferencesWindow(EsgPreferencesService prefs)
    {
        _prefs = prefs;
        InitializeComponent();
        LoadFrom(_prefs.Current);
    }

    private void LoadFrom(EsgPreferences p)
    {
        WeaponsCheck.IsChecked = p.EnabledPresets.Contains("weapons", StringComparer.OrdinalIgnoreCase);
        TobaccoCheck.IsChecked = p.EnabledPresets.Contains("tobacco", StringComparer.OrdinalIgnoreCase);
        FossilCheck.IsChecked = p.EnabledPresets.Contains("fossil_fuels", StringComparer.OrdinalIgnoreCase);
        GamblingCheck.IsChecked = p.EnabledPresets.Contains("gambling", StringComparer.OrdinalIgnoreCase);
        TickersBox.Text = string.Join(", ", p.ExcludedTickers);
        NamesBox.Text = string.Join(", ", p.ExcludedNameKeywords);
        SectorsBox.Text = string.Join(", ", p.CustomSectorKeywords);
        EsgMinBox.Text = p.EsgMinScore?.ToString("0") ?? "";
    }

    private void OnOk(object sender, RoutedEventArgs e)
    {
        var presets = new List<string>();
        if (WeaponsCheck.IsChecked == true) presets.Add("weapons");
        if (TobaccoCheck.IsChecked == true) presets.Add("tobacco");
        if (FossilCheck.IsChecked == true) presets.Add("fossil_fuels");
        if (GamblingCheck.IsChecked == true) presets.Add("gambling");

        double? esgMin = null;
        if (!string.IsNullOrWhiteSpace(EsgMinBox.Text))
        {
            if (!double.TryParse(EsgMinBox.Text.Trim(), out var parsed) || parsed is < 0 or > 100)
            {
                MessageBox.Show("ESG minimum must be a number between 0 and 100.", "Riskbot",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            esgMin = parsed;
        }

        var draft = new EsgPreferences
        {
            EnabledPresets = presets,
            ExcludedTickers = SplitList(TickersBox.Text),
            ExcludedNameKeywords = SplitList(NamesBox.Text),
            CustomSectorKeywords = SplitList(SectorsBox.Text),
            EsgMinScore = esgMin,
        };
        var sanitized = EsgPreferencesValidator.Sanitize(draft);
        if (sanitized.ExcludedTickers.Count < draft.ExcludedTickers.Count
            || sanitized.ExcludedNameKeywords.Count < draft.ExcludedNameKeywords.Count)
        {
            MessageBox.Show(
                "Some entries were ignored (invalid ticker symbols or unsafe keywords).",
                "Riskbot",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }

        _prefs.Update(sanitized);
        DialogResult = true;
        Close();
    }

    private static List<string> SplitList(string text) =>
        text.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Where(s => s.Length > 0)
            .ToList();
}
