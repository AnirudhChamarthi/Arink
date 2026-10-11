namespace Riskbot.App.Services;

/// <summary>App-wide ESG / exclusion preferences.</summary>
public sealed class EsgPreferencesService
{
    private readonly EsgPreferencesStore _store;
    private Models.EsgPreferences _current;

    public EsgPreferencesService(EsgPreferencesStore store)
    {
        _store = store;
        _current = store.Load();
    }

    public Models.EsgPreferences Current => _current;

    public event Action? PreferencesChanged;

    public void Update(Models.EsgPreferences prefs)
    {
        _current = prefs;
        _store.Save(prefs);
        PreferencesChanged?.Invoke();
    }
}
