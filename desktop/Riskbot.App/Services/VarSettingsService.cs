namespace Riskbot.App.Services;

/// <summary>User-selected VaR parameters for treemap and /risk/var calls.</summary>
public sealed class VarSettingsService
{
    private readonly VarSettingsStore _store;

    public VarSettingsService(VarSettingsStore store)
    {
        _store = store;
        var saved = _store.Load();
        Method = saved.Method;
        Confidence = saved.Confidence;
        HorizonDays = saved.HorizonDays;
    }

    public string Method { get; private set; } = "parametric";

    public double Confidence { get; private set; } = 0.99;

    public int HorizonDays { get; private set; } = 1;

    public event Action? SettingsChanged;

    public void Update(string method, double confidence, int horizonDays)
    {
        Method = method;
        Confidence = confidence;
        HorizonDays = horizonDays;
        _store.Save(new VarSettingsSnapshot
        {
            Method = method,
            Confidence = confidence,
            HorizonDays = horizonDays,
        });
        SettingsChanged?.Invoke();
    }
}
