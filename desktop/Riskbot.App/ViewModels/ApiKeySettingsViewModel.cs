using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Riskbot.App.Infrastructure;
using Riskbot.App.Services;

namespace Riskbot.App.ViewModels;

public sealed partial class ApiKeySettingsViewModel : ObservableObject
{
    private readonly EnvFileStore _envStore;
    private readonly EngineHostService _engine;

    public ApiKeySettingsViewModel(EnvFileStore envStore, EngineHostService engine)
    {
        _envStore = envStore;
        _engine = engine;
    }

    [ObservableProperty]
    private string _apiKey = "";

    [ObservableProperty]
    private bool _showKey;

    [ObservableProperty]
    private string _envFilePath = "";

    [ObservableProperty]
    private string _statusMessage = "";

    [ObservableProperty]
    private string _gitNotice =
        "Your API key is saved in .env on this computer only. That file is gitignored — it is never pushed to Git. " +
        "Use Help → API Key Settings to manage it; .env is created automatically from .env.example if missing.";

    [ObservableProperty]
    private bool _hasStoredKey;

    [ObservableProperty]
    private bool _canSave = true;

    public event Action<bool>? RequestClose;

    public void Load()
    {
        if (_envStore.RepoRoot is null)
        {
            StatusMessage = "Could not find the Riskbot project folder. Open the app from a cloned repo.";
            CanSave = false;
            return;
        }

        var created = false;
        if (!_envStore.EnsureEnvFileExists(out created))
        {
            StatusMessage = "Could not create .env file.";
            CanSave = false;
            return;
        }

        EnvFilePath = _envStore.EnvFilePath ?? "";
        ApiKey = _envStore.GetValue(EnvFileStore.AnthropicApiKeyName) ?? "";
        HasStoredKey = !string.IsNullOrWhiteSpace(ApiKey);
        StatusMessage = created
            ? "Created .env from .env.example — add your key below and click Save."
            : HasStoredKey
                ? "A key is stored locally. Edit or clear it below."
                : "No key stored — NLQ uses keyword routing until you add one.";
        CanSave = true;
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        if (!CanSave)
            return;

        var trimmed = ApiKey.Trim();
        _envStore.SetValue(EnvFileStore.AnthropicApiKeyName, trimmed);
        _envStore.ApplyToProcessEnvironment(EnvFileStore.AnthropicApiKeyName, trimmed);

        HasStoredKey = !string.IsNullOrWhiteSpace(trimmed);
        StatusMessage = HasStoredKey
            ? "Saved. Restarting engine so NLQ picks up the new key…"
            : "Cleared. Restarting engine…";

        await ApplyEngineRestartMessageAsync().ConfigureAwait(true);

        StatusMessage = HasStoredKey
            ? "Key saved to .env (local only, not in Git)."
            : "Key cleared. NLQ will use keyword routing.";

        RequestClose?.Invoke(true);
    }

    [RelayCommand]
    private async Task ClearKeyAsync()
    {
        ApiKey = "";
        _envStore.ClearValue(EnvFileStore.AnthropicApiKeyName);
        _envStore.ApplyToProcessEnvironment(EnvFileStore.AnthropicApiKeyName, null);

        HasStoredKey = false;
        StatusMessage = "Key removed from .env. Restarting engine…";
        await ApplyEngineRestartMessageAsync().ConfigureAwait(true);
        StatusMessage = "Key deleted. NLQ will use keyword routing.";
        RequestClose?.Invoke(true);
    }

    [RelayCommand]
    private void Cancel() => RequestClose?.Invoke(false);

    private async Task ApplyEngineRestartMessageAsync()
    {
        var restarted = await _engine.RestartAsync().ConfigureAwait(true);
        if (!restarted)
        {
            StatusMessage += " If NLQ still uses the old key, restart the app or stop the engine on port 8765.";
        }
    }
}
