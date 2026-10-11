# `Riskbot.App.Tests` — xUnit tests for the desktop layer

Tests everything **below the OpenAPI boundary** on the C# side: file parsing, limits, message bus, NLQ client behavior (mocked HTTP), RTD security, env file handling.

## Why C# tests here (not only Python)?

| Area | Python tests insufficient because |
|------|-----------------------------------|
| `PortfolioFileManager` | Open XML parsing, sheet layout per `portfolio_schema.json` |
| `RiskLimitMonitor` | Synchronous breach rules on `BlotterRow` |
| `MessageBus` | Channel fan-out ordering |
| `NlqService` | Cancellation, generation guards, error sanitization |
| RTD | Path validation, snapshot limits |

Engine pytest does not compile XAML or run COM.

## Representative test files

| File | Covers |
|------|--------|
| `PortfolioFileManagerTests.cs` | xlsx → `PortfolioFile` |
| `RiskLimitMonitorTests.cs` | VaR/concentration/ESG/exclusion breaches |
| `RiskLimitMonitorBusIntegrationTests.cs` | Bus → breach events |
| `NlqServiceTests.cs` | Mock `HttpClient` / API client |
| `MessageBusTests.cs` | Pub/sub |
| `SquarifiedTreemapLayoutTests.cs` | Layout geometry |
| `RtdSnapshotTests.cs`, `RtdSecurityTests.cs` | RTD bridge |
| `Step10SecurityTests.cs`, `Step11SecurityTests.cs` | Report path / NLQ injection guards |

## Run

```powershell
cd desktop
dotnet test Riskbot.App.Tests\Riskbot.App.Tests.csproj
```

WPF UI automation is **out of scope**.

Parent: [../README.md](../README.md) · Engine tests: [../../engine/tests/README.md](../../engine/tests/README.md)
