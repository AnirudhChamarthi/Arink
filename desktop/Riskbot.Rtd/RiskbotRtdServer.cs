using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using ExcelDna.Integration;
using ExcelDna.Integration.Rtd;
using Riskbot.RtdBridge;

namespace Riskbot.Rtd;

/// <summary>
/// Excel RTD server — use in Excel:
/// =RTD("Riskbot.RTD",,"AAPL","CurrentPrice")
/// Requires Riskbot desktop with an enriched portfolio (writes rtd_snapshot.json).
/// </summary>
[ComVisible(true)]
[ProgId(RtdSnapshot.ProgId)]
[Guid("8f3c2e1a-4b5d-6c7e-9f0a-1b2c3d4e5f60")]
public sealed class RiskbotRtdServer : ExcelRtdServer
{
    private readonly object _sync = new();
    private readonly List<SubscribedTopic> _topics = new();
    private Timer? _pollTimer;
    private RtdSnapshot? _cache;
    private DateTimeOffset _cacheUpdatedUtc = DateTimeOffset.MinValue;

    protected override bool ServerStart()
    {
        _pollTimer = new Timer(_ => PollSnapshotAndPush(), null, TimeSpan.Zero, TimeSpan.FromSeconds(1));
        return true;
    }

    protected override void ServerTerminate()
    {
        _pollTimer?.Dispose();
        _pollTimer = null;
        lock (_sync)
        {
            _topics.Clear();
            _cache = null;
            _cacheUpdatedUtc = DateTimeOffset.MinValue;
        }
    }

    protected override object ConnectData(Topic topic, IList<string> topicInfo, ref bool newValues)
    {
        if (topicInfo.Count < 2
            || !RtdTopicValidator.TryNormalize(topicInfo[0], topicInfo[1], out var ticker, out var field))
            return ExcelErrorUtil.ToComError(ExcelError.ExcelErrorValue);

        lock (_sync)
        {
            if (_topics.Count >= RtdSnapshotLimits.MaxExcelSubscriptions)
                return ExcelErrorUtil.ToComError(ExcelError.ExcelErrorValue);

            _topics.Add(new SubscribedTopic(topic, ticker, field));
            if (_cache?.TryGetValue(ticker, field, out var cached) == true)
                return cached;
        }

        newValues = true;
        return ExcelErrorUtil.ToComError(ExcelError.ExcelErrorNA);
    }

    protected override void DisconnectData(Topic topic)
    {
        lock (_sync)
        {
            for (var i = _topics.Count - 1; i >= 0; i--)
            {
                if (ReferenceEquals(_topics[i].Topic, topic))
                    _topics.RemoveAt(i);
            }
        }
    }

    private void PollSnapshotAndPush()
    {
        var snapshot = RtdSnapshotFile.TryRead();
        if (snapshot is null)
            return;

        List<SubscribedTopic> topics;
        lock (_sync)
        {
            _cache = snapshot;
            _cacheUpdatedUtc = snapshot.UpdatedUtc;
            topics = new List<SubscribedTopic>(_topics);
        }

        foreach (var sub in topics)
        {
            var value = snapshot.TryGetValue(sub.Ticker, sub.Field, out var v)
                ? v
                : ExcelErrorUtil.ToComError(ExcelError.ExcelErrorNA);
            sub.Topic.UpdateValue(value);
        }
    }

    private sealed class SubscribedTopic
    {
        public SubscribedTopic(Topic topic, string ticker, string field)
        {
            Topic = topic;
            Ticker = ticker;
            Field = field;
        }

        public Topic Topic { get; }
        public string Ticker { get; }
        public string Field { get; }
    }
}
