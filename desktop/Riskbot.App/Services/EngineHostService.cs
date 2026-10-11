using System.Diagnostics;
using Riskbot.App.ApiClient;
using Riskbot.App.Infrastructure;

namespace Riskbot.App.Services;

public enum EngineConnectionState
{
    Starting,
    Online,
    Offline,
    Error,
}

public sealed class EngineHostService : IAsyncDisposable
{
    public const string BaseUrl = "http://127.0.0.1:8765/";

    private readonly RiskbotApiClient _api;
    private Process? _process;
    private readonly object _processLock = new();

    public EngineConnectionState State { get; private set; } = EngineConnectionState.Offline;
    public string StatusMessage { get; private set; } = "Engine: starting…";

    public event Action? StatusChanged;

    public EngineHostService(RiskbotApiClient api) => _api = api;

    public async Task EnsureRunningAsync(CancellationToken cancellationToken = default)
    {
        SetState(EngineConnectionState.Starting, "Engine: starting…");

        if (await IsHealthyAsync(cancellationToken).ConfigureAwait(false))
        {
            SetState(EngineConnectionState.Online, "Engine: online");
            return;
        }

        if (!TrySpawnEngine())
        {
            SetState(EngineConnectionState.Error, "Engine: could not start (see logs)");
            return;
        }

        for (var i = 0; i < 60; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Delay(500, cancellationToken).ConfigureAwait(false);
            if (await IsHealthyAsync(cancellationToken).ConfigureAwait(false))
            {
                SetState(EngineConnectionState.Online, "Engine: online");
                return;
            }
        }

        SetState(EngineConnectionState.Error, "Engine: timeout waiting for /health");
    }

    private async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        var health = await _api.GetHealthAsync(cancellationToken).ConfigureAwait(false);
        return health is { Status: "ok" };
    }

    private bool TrySpawnEngine()
    {
        var engineDir = RepoPaths.FindEngineDirectory();
        if (engineDir is null)
        {
            SetState(EngineConnectionState.Error, "Engine: engine/ folder not found");
            return false;
        }

        var python = Environment.GetEnvironmentVariable("RISKBOT_PYTHON") ?? "python";
        var startInfo = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-m uvicorn main:app --host 127.0.0.1 --port 8765",
            WorkingDirectory = engineDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };

        EngineEnvironment.ApplyTo(startInfo, new EnvFileStore());

        try
        {
            lock (_processLock)
            {
                _process?.Dispose();
                _process = Process.Start(startInfo);
            }
            return _process is not null;
        }
        catch (Exception ex)
        {
            SetState(EngineConnectionState.Error, $"Engine: {ex.Message}");
            return false;
        }
    }

    private void SetState(EngineConnectionState state, string message)
    {
        State = state;
        StatusMessage = message;
        StatusChanged?.Invoke();
    }

    public async Task<bool> RestartAsync(CancellationToken cancellationToken = default)
    {
        Process? proc;
        lock (_processLock)
        {
            proc = _process;
            _process = null;
        }

        if (proc is null)
            return false;

        try
        {
            if (!proc.HasExited)
            {
                proc.Kill(entireProcessTree: true);
                await proc.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            }
        }
        catch
        {
            // Best effort — still try to spawn a fresh child.
        }
        finally
        {
            proc.Dispose();
        }

        await EnsureRunningAsync(cancellationToken).ConfigureAwait(false);
        return true;
    }

    public async ValueTask DisposeAsync()
    {
        Process? proc;
        lock (_processLock)
        {
            proc = _process;
            _process = null;
        }

        if (proc is null)
            return;

        try
        {
            if (!proc.HasExited)
            {
                proc.Kill(entireProcessTree: true);
                await proc.WaitForExitAsync().ConfigureAwait(false);
            }
        }
        catch
        {
            // Best effort on shutdown.
        }
        finally
        {
            proc.Dispose();
        }
    }
}
