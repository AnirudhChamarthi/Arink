# `shared/` — contracts and reference data

Language-neutral artifacts that **both** the Python engine and the C# desktop must honor. Nothing in this folder executes at runtime; it is the **constitution** of the system and was the first thing built.

## Contents

| File | Purpose |
|------|---------|
| [`openapi.yaml`](openapi.yaml) | REST API: request/response schemas, endpoints, examples |
| [`portfolio_schema.json`](portfolio_schema.json) | Structure of the portfolio `.xlsx` (Holdings + Metadata sheets) |
| [`scenarios.json`](scenarios.json) | Named stress scenarios (shocks by asset class / factor) |

## Why not Python or C# here?

Contracts are kept in **portable, diff-friendly formats** so:

- API changes are reviewed without recompiling either side.
- Future clients (CLI, web dashboard, CI fixtures) can adopt the same files.
- OpenAPI tooling (codegen, mock servers, contract tests) stays optional.

YAML/JSON beats embedding types only in Python (`pydantic`) or C# (`ContractModels.cs`) because those copies **drift** unless anchored to one file.

## `openapi.yaml` — HTTP boundary

Defines the local engine at `http://127.0.0.1:8765`:

| Endpoint | Consumer in desktop | Implementer in engine |
|----------|---------------------|------------------------|
| `GET /health` | `RiskbotApiClient.GetHealthAsync` → `EngineHostService` | `api/routes/health.py` |
| `POST /enrich` | `EnrichmentService` → `RiskbotApiClient.EnrichAsync` | `api/routes/enrich.py` → `services/enrich.py` |
| `POST /nlq` | `NlqService` | `api/routes/nlq.py` → `nlp/executor.py` |
| `POST /risk/var` | `PortfolioRiskService`, `RiskAnalysisService` | `api/routes/risk.py` → `models/var.py` |
| `POST /risk/greeks` | same | `models/greeks.py` |
| `POST /risk/stress` | same | `models/stress.py` + `shared/scenarios.json` |
| `POST /risk/sustainability` | same | `models/sustainability.py` |
| `POST /risk/garch` | same | `models/garch.py` |
| `POST /risk/full-report` | Full risk report menu | `reports/master_report.py` |

Key schema concepts mirrored on both sides:

- **`RawPosition`** / **`EnrichedPosition`** — blotter row before/after market data
- **`EnrichedPortfolio`** — full book + `portfolio_session_id` after enrich
- **`NlqResult`** — topline metric, formula breakdown, explanation, `report_path`
- **`RiskLimits`** — VaR cap, concentration, ESG floor, exclusions (from metadata + app prefs)

### Downstream implementations

| OpenAPI consumer | File |
|------------------|------|
| Python request/response types | [`engine/schemas/contract.py`](../engine/schemas/contract.py) |
| C# DTOs | [`desktop/Riskbot.App/ApiClient/ContractModels.cs`](../desktop/Riskbot.App/ApiClient/ContractModels.cs) |
| HTTP calls | [`desktop/Riskbot.App/ApiClient/RiskbotApiClient.cs`](../desktop/Riskbot.App/ApiClient/RiskbotApiClient.cs) |

When you change `openapi.yaml`, update **both** `contract.py` and `ContractModels.cs`, then adjust route handlers and client call sites.

## `portfolio_schema.json` — Excel file shape

Describes the workbook the desk user edits—not the API.

| Sheet | Used by |
|-------|---------|
| Holdings | `PortfolioFileManager` → `RawPosition` list |
| Metadata | `PortfolioMetadata`, `RiskLimitsMapper`, `RiskLimitMonitor` |

Fields like `VaRLimit`, `MaxConcentration`, and `ExclusionFilters` on Metadata drive **client-side** breach highlighting (`RiskLimitMonitor`) and are also sent to the engine on NLQ/risk calls as `RiskLimits`.

**Why JSON schema instead of OpenAPI?** The portfolio file is not HTTP; a separate schema keeps file-validation docs clear and lets the desktop validate before any network call.

## `scenarios.json` — stress test catalog

Loaded by [`engine/models/stress.py`](../engine/models/stress.py) for named scenarios (e.g. rate shock, equity crash). Custom shocks can still be posted in the API body per OpenAPI.

Desktop does not parse this file directly; stress names must match what users type in NLQ or future UI scenario pickers.

## Competitive advantage of a shared contract layer

| Approach | Drawback |
|----------|----------|
| Ad-hoc JSON between teams | Silent field renames break production |
| gRPC/protobuf only | Heavier for local loopback + manual curl debugging |
| Duplicate DTOs without spec | C# `EnrichResponse` and Python `EnrichResponse` diverge |

OpenAPI + JSON Schema here gives **inspectable, versionable** agreements with optional Swagger UI at `/docs` when the engine runs.

## Related docs

- [../README.md](../README.md) — system overview
- [../engine/README.md](../engine/README.md) — server implementation
- [../desktop/README.md](../desktop/README.md) — client implementation
- [../samples/README.md](../samples/README.md) — example portfolio file
