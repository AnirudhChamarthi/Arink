# `engine/schemas/` — Pydantic contract types

Python representation of [`shared/openapi.yaml`](../../shared/openapi.yaml). Every route `response_model` and request body flows through here.

## Primary file

[`contract.py`](contract.py) — `RawPosition`, `EnrichedPosition`, `EnrichedPortfolio`, `VarRequest`/`VarResult`, `NlqResult`, `RiskLimits`, stress/GARCH/sustainability types, etc.

## Why Pydantic (Python)?

- **Automatic validation** on ingress—bad desktop payloads fail fast with 422.
- **Single source** aligned with OpenAPI; FastAPI emits matching `/docs`.
- **Enum safety** — e.g. `AssetClass`, `VarMethod`, `StressScenario`.

**vs C# records only:** Python engine would lack runtime validation without duplicate FluentValidation.

**vs dataclasses alone:** No JSON schema generation or coercion (dates, optional chains).

## Mirror on desktop

[`ContractModels.cs`](../../desktop/Riskbot.App/ApiClient/ContractModels.cs) — must be updated in lockstep when `openapi.yaml` changes.

[`PortfolioFileManager`](../../desktop/Riskbot.App/ExcelIntegration/PortfolioFileManager.cs) maps xlsx rows to `RawPosition`-compatible DTOs before HTTP—not via this module directly, but same field names as `shared/portfolio_schema.json`.

## Usage map

| Consumer | Imports from `schemas.contract` |
|----------|----------------------------------|
| `api/routes/*` | Request/response models |
| `models/*` | Result types |
| `nlp/executor.py` | `NlqResult`, `EnrichedPortfolio` |
| `services/enrich.py` | `EnrichRequest`, `EnrichResponse` |

Parent: [../README.md](../README.md) · Spec: [../../shared/README.md](../../shared/README.md)
