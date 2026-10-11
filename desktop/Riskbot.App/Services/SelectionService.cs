namespace Riskbot.App.Services;

/// <summary>Shared selection between blotter and treemap.</summary>
public sealed class SelectionService
{
    private string? _selectedTicker;

    public string? SelectedTicker
    {
        get => _selectedTicker;
        set
        {
            if (string.Equals(_selectedTicker, value, StringComparison.OrdinalIgnoreCase))
                return;
            _selectedTicker = value;
            SelectionChanged?.Invoke(value);
        }
    }

    public event Action<string?>? SelectionChanged;

    public void Select(string? ticker) => SelectedTicker = ticker;
}
