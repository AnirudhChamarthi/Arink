# `Riskbot.RtdBridge` — RTD snapshot contract (shared library)

Small **.NET class library** referenced by both `Riskbot.App` and `Riskbot.Rtd`. Holds the JSON snapshot shape, allowed fields, path resolution, and rate limits—without pulling WPF or Excel-DNA into the main app unnecessarily.

## Why a separate project?

| Benefit | Explanation |
|---------|-------------|
| Single source of truth | App writer and RTD reader use identical `RtdSnapshot` types |
| Lighter RTD build | Excel add-in DLL stays minimal |
| Testability | Snapshot parsing tests without loading WPF |

## Key files

| File | Role |
|------|------|
| [`RtdSnapshot.cs`](RtdSnapshot.cs) | DTO + `ProgId` constant (`Riskbot.RTD`) |
| [`RtdSnapshotFile.cs`](RtdSnapshotFile.cs) | Atomic read/write helpers |
| [`RtdSnapshotPath.cs`](RtdSnapshotPath.cs) | Per-user snapshot path under AppData |
| [`RtdFields.cs`](RtdFields.cs) | Allowed metric names (`CurrentPrice`, Greeks, etc.) |
| [`RtdTopicValidator.cs`](RtdTopicValidator.cs) | Reject malformed ticker/field topics |
| [`RtdSnapshotLimits.cs`](RtdSnapshotLimits.cs) | Cap row count / payload size |

## Link to Python engine

**Indirect only:** App fills snapshot from enriched positions and cached `PortfolioRiskService` / Greeks API results, which originated from `engine/` endpoints.

## Link to Excel

[`Riskbot.Rtd/RiskbotRtdServer.cs`](../Riskbot.Rtd/RiskbotRtdServer.cs) polls snapshot every second and pushes new values to subscribed topics.

Parent: [../README.md](../README.md)
