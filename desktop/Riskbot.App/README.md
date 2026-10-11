# `Riskbot.App` — WPF main application

The executable traders run. Four-zone shell: **blotter** (left), **treemap** (right), **NLQ bar** (bottom), **result panel** (bottom-right).

## Why C# here (not Python)?

This project owns **interaction latency** and **Windows integration**:

- DataGrid with per-cell flash animations (`Behaviors/FlashingCell`)
- Squarified treemap layout ([`Helpers/SquarifiedTreemapLayout.cs`](Helpers/SquarifiedTreemapLayout.cs))
- Modal settings (VaR, ESG, API key, model docs)
- No Excel COM required for portfolio load (Open XML only)

## Folder map

| Folder | Purpose | Key files |
|--------|---------|-----------|
| [`ApiClient/`](ApiClient/) | HTTP to engine | `RiskbotApiClient.cs`, `ContractModels.cs` |
| [`Bus/`](Bus/) | In-process events | `MessageBus.cs`, `Events/*.cs` |
| [`ExcelIntegration/`](ExcelIntegration/) | `.xlsx` read/write | `PortfolioFileManager.cs`, `TemplateWriter.cs` |
| [`Infrastructure/`](Infrastructure/) | Paths, `.env` | `RepoPaths.cs`, `EnvFileLoader.cs`, `EnvFileStore.cs` |
| [`Services/`](Services/) | App logic | See table below |
| [`ViewModels/`](ViewModels/) | MVVM state | `MainViewModel.cs`, `BlotterViewModel.cs`, `TreemapViewModel.cs`, `NlqViewModel.cs`, `ResultViewModel.cs` |
| [`Views/`](Views/) | XAML UI | `MainWindow.xaml`, `BlotterView.xaml`, `TreemapView.xaml`, `NlqPanel.xaml`, `ResultPanel.xaml` |
| [`Models/`](Models/) | UI row types | `BlotterRow.cs`, `PortfolioMetadata.cs` |
| [`Helpers/`](Helpers/) | Mappers, docs, NLQ safety | `RiskLimitsMapper.cs`, `ModelDocumentation.cs` |

## Services (engine touchpoints)

| Service | Engine API | Trigger |
|---------|------------|---------|
| [`EngineHostService`](Services/EngineHostService.cs) | `GET /health` | App startup |
| [`EnrichmentService`](Services/EnrichmentService.cs) | `POST /enrich` | `PortfolioLoadedEvent`, refresh |
| [`NlqService`](Services/NlqService.cs) | `POST /nlq` | NLQ submit |
| [`PortfolioRiskService`](Services/PortfolioRiskService.cs) | `/risk/var`, `/risk/garch`, … | VaR settings, background risk |
| [`RiskAnalysisService`](Services/RiskAnalysisService.cs) | `POST /risk/full-report` | Risk menu |
| [`RtdFeedService`](Services/RtdFeedService.cs) | (local file) | Writes RTD snapshot for Excel |

**Client-only** (no engine):

| Service | Role |
|---------|------|
| [`RiskLimitMonitor`](Services/RiskLimitMonitor.cs) | Concentration, VaR limit, ESG, exclusions on `PositionUpdatedEvent` |
| [`PortfolioWorkspaceService`](Services/PortfolioWorkspaceService.cs) | Open/save/recent files |
| [`EsgPreferencesService`](Services/EsgPreferencesService.cs) | App-wide exclusion prefs merged into limits |

## UI ↔ bus ↔ API flow (enrichment)

```
File → Open → PortfolioFileManager
  → PortfolioLoadedEvent
  → EnrichmentService → RiskbotApiClient.EnrichAsync
  → EnrichmentCompleteEvent (per ticker)
  → BlotterViewModel updates + FlashingCell
  → PortfolioSessionState.PortfolioSessionId
```

## UI ↔ NLQ

```
NlqPanel → NlqViewModel → NlqService.SubmitAsync
  → POST /nlq
  → NlqResultEvent → ResultViewModel
  → Optional: NlqReportPathValidator → Process.Start(excel)
```

## Treemap ↔ blotter linking

[`TreemapViewModel`](ViewModels/TreemapViewModel.cs) + [`SelectionService`](Services/SelectionService.cs) — click/hover syncs ticker highlight both ways; colour modes (Exposure, ESG, Carbon, VaR contribution) use enriched fields from last API responses.

## Views of note

| View | Feature |
|------|---------|
| `VarSettingsWindow` | Confidence, horizon, method → `VarSettingsStore` |
| `EsgPreferencesWindow` | Exclusion strings → merged into `RiskLimits` |
| `ModelDocumentationWindow` | Static help from `Helpers/ModelDocumentation.cs` |
| `RtdFormulasWindow` | Copy-paste RTD formulas |
| `Views/Treemap/SquarifiedTreemapPanel` | Custom layout control |

## Startup wiring

[`App.xaml.cs`](App.xaml.cs) — constructs singletons, shows [`MainWindow.xaml`](MainWindow.xaml), eagerly resolves hosted services so bus subscriptions are active.

Parent: [../README.md](../README.md) · Engine: [../../engine/README.md](../../engine/README.md)
