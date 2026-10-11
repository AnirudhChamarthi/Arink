using System.Threading.Channels;

namespace Riskbot.App.Bus;

/// <summary>In-process event bus (single publisher, fan-out subscribers).</summary>
public sealed class MessageBus : IAsyncDisposable
{
    private readonly Channel<IRiskEvent> _channel = Channel.CreateUnbounded<IRiskEvent>();
    private readonly List<(Type Type, Delegate Handler)> _handlers = [];
    private readonly object _lock = new();
    private readonly CancellationTokenSource _cts = new();
    private Task? _pump;

    public MessageBus() => _pump = Task.Run(PumpAsync);

    public async Task PublishAsync<T>(T evt) where T : IRiskEvent
    {
        await _channel.Writer.WriteAsync(evt);
    }

    public void Subscribe<T>(Func<T, Task> handler) where T : IRiskEvent
    {
        lock (_lock)
        {
            _handlers.Add((typeof(T), handler));
        }
    }

    private async Task PumpAsync()
    {
        await foreach (var evt in _channel.Reader.ReadAllAsync(_cts.Token))
        {
            List<(Type Type, Delegate Handler)> snapshot;
            lock (_lock)
                snapshot = _handlers.ToList();

            foreach (var (type, handler) in snapshot)
            {
                if (!type.IsInstanceOfType(evt))
                    continue;
                try
                {
                    var task = (Task)handler.DynamicInvoke(evt)!;
                    await task.ConfigureAwait(false);
                }
                catch
                {
                    // Subscribers must not break the pump; log in Step 4.
                }
            }
        }
    }

    public async ValueTask DisposeAsync()
    {
        _channel.Writer.TryComplete();
        _cts.Cancel();
        if (_pump is not null)
        {
            try { await _pump.ConfigureAwait(false); }
            catch (OperationCanceledException) { }
        }
        _cts.Dispose();
    }
}
