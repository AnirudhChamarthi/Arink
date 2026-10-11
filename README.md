# Riskbot (SustainableC)

Riskbot is a **portfolio risk workstation**: a Windows WPF desktop client talks to a local **Python quantitative engine** over HTTP. Market data, VaR, Greeks, GARCH, stress tests, ESG/sustainability metrics, natural-language queries (NLQ), and Excel outputs all flow through a single **OpenAPI contract** in `shared/`.

## Quick start

Requires **Windows**, the **.NET 8 SDK**, and **Python 3.11+**.

```powershell
git clone https://github.com/AnirudhChamarthi/Arink.git
cd Arink

pip install -r engine\requirements.txt
copy .env.example .env          # optional: add ANTHROPIC_API_KEY for Claude-powered questions

dotnet run --project desktop\Riskbot.App\Riskbot.App.csproj
```

The app starts the Python engine automatically. Open `samples\SamplePortfolio.xlsx` from **File → Open Portfolio…**, wait for the blotter to fill in, then ask a question such as *"What is my parametric VaR?"*. Full setup, testing, and troubleshooting: **[RUN.md](RUN.md)**.

## Configuration

All settings live in a `.env` file in the repository root. Copy [`.env.example`](.env.example) to `.env` and fill in what you need; `.env` is gitignored so your keys stay on your machine.

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | No | Claude routing and explanations for natural-language questions. Without it, a keyword router is used. |
| `ANTHROPIC_MODEL` | No | Override the Claude model id. |
| `OPENFIGI_API_KEY` | No | Higher rate limits for ISIN → ticker lookup. |
| `RISKBOT_PYTHON` | No | Python interpreter the desktop app uses to start the engine (default: `python` on PATH). |
| `RISKBOT_CACHE_DIR` | No | Market-data cache location (default: `engine/.cache`). |

You can also set the API key inside the app under **Help → API Key Settings**.

## What is not in the repository

These are generated locally and gitignored: `.env` (your secrets), `engine/.cache/` (market-data cache), `engine/output/reports/` (generated Excel reports), and `bin/` / `obj/` build output. Market and ESG data are fetched at runtime; the ESG and carbon values in `engine/data/sample_*.csv` are illustrative sample data, not a licensed dataset.

## Repository map

| Folder | Role | Primary language | Deep dive |
|--------|------|------------------|-----------|
| [`shared/`](shared/README.md) | API contract, portfolio file schema, stress scenarios | YAML / JSON (language-neutral) | [shared/README.md](shared/README.md) |
| [`engine/`](engine/README.md) | FastAPI server: enrichment, models, NLQ, Excel reports | **Python** | [engine/README.md](engine/README.md) |
| [`desktop/`](desktop/README.md) | WPF UI, Excel I/O, RTD add-in, engine lifecycle | **C#** | [desktop/README.md](desktop/README.md) |
| [`samples/`](samples/README.md) | Sample `.xlsx` portfolio and generator script | Python (generator only) | [samples/README.md](samples/README.md) |

Operational run instructions: **[RUN.md](RUN.md)**.

## Why two languages?

The split is intentional **separation of concerns**, not polyglot novelty:

| Concern | Language | Rationale |
|---------|----------|-----------|
| Numerics, stats, ML-adjacent libs, report charts | **Python** | `numpy`, `scipy`, `arch`, `matplotlib`, `yfinance`, `anthropic` — mature quant/data stack with short iteration cycles |
| Desktop UI, Excel integration, COM RTD, process hosting | **C# / .NET** | WPF, Open XML SDK, Excel-DNA, `System.Threading.Channels` — first-class Windows desktop and Office interop |
| Contract between them | **OpenAPI** | One source of truth; both sides validate shapes without sharing a runtime |

**Python vs alternatives (engine):** R/Julia excel at stats but weak HTTP/service ergonomics and Excel report tooling; Java/Kotlin lack the same density of free market-data and quant libraries for a solo-dev loop; C++ would be faster but slower to ship and harder to bind for NLQ/report generation.

**C# vs alternatives (desktop):** Electron/React would not give native WPF performance, COM RTD, or clean child-process hosting of Python; JavaFX is weaker on Windows Excel paths; Python-only UI (PyQt) would duplicate Office integration work and fight the GIL for a responsive blotter.

## End-to-end data flow

```mermaid
flowchart LR
  subgraph desktop [desktop - C#]
    XLSX[Portfolio .xlsx]
    PFM[PortfolioFileManager]
    BUS[MessageBus]
    API[RiskbotApiClient]
    UI[WPF Views / ViewModels]
    RTD[RtdFeedService]
    XLSX --> PFM
    PFM --> BUS
    BUS --> UI
    API --> BUS
    RTD --> Excel[Excel RTD add-in]
  end

  subgraph shared [shared]
    OAS[openapi.yaml]
    PSC[portfolio_schema.json]
    SCN[scenarios.json]
  end

  subgraph engine [engine - Python]
    UV[main.py / uvicorn]
    ENR[/enrich]
    NLQ[/nlq]
    RISK[/risk/*]
    SESS[portfolio_session_store]
    UV --> ENR
    UV --> NLQ
    UV --> RISK
    ENR --> SESS
    RISK --> SESS
    NLQ --> SESS
  end

  PFM -. validates .-> PSC
  API <-- HTTP JSON --> OAS
  API --> UV
  OAS -. implemented by .-> UV
  SCN -. loaded by .-> RISK
```

Typical session:

1. User opens `samples/SamplePortfolio.xlsx` → `PortfolioFileManager` reads holdings + metadata (`shared/portfolio_schema.json`).
2. `PortfolioLoadedEvent` → `EnrichmentService` → `POST /enrich` → engine stores full portfolio under `portfolio_session_id`, returns display fields.
3. Blotter/treemap update via bus events; `RiskLimitMonitor` checks limits from metadata.
4. NLQ or **Risk** menu → `POST /nlq` or `/risk/var` etc., using `portfolio_session_id`.
5. Optional: `RtdFeedService` writes `rtd_snapshot.json` for Excel `=RTD("Riskbot.RTD",...)`.

## Major cross-folder links

| From | To | Mechanism |
|------|-----|-----------|
| `desktop/.../ContractModels.cs` | `shared/openapi.yaml` | Hand-maintained DTOs mirroring OpenAPI schemas |
| `engine/schemas/contract.py` | `shared/openapi.yaml` | Pydantic models aligned to the same shapes |
| `desktop/.../PortfolioFileManager.cs` | `shared/portfolio_schema.json` | Column/sheet layout for `.xlsx` |
| `engine/models/stress.py` | `shared/scenarios.json` | Named stress scenario definitions |
| `desktop/.../EngineHostService.cs` | `engine/main.py` | Spawns `python -m uvicorn main:app --port 8765` |
| `engine/reports/excel_writer.py` | `engine/output/reports/` | NLQ/full-report workbooks consumed by desktop “Open Excel Report” |
| `desktop/Riskbot.Rtd` | `desktop/Riskbot.RtdBridge` | Snapshot file contract for live Excel cells |
| Repo `.env` | `engine/main.py`, `desktop/.../EnvFileLoader.cs` | `ANTHROPIC_API_KEY` for Claude NLQ routing |

## Engine subfolders

See [engine/README.md](engine/README.md) and nested docs:

- [engine/api/README.md](engine/api/README.md) — HTTP routes
- [engine/models/README.md](engine/models/README.md) — VaR, Greeks, GARCH, stress, sustainability
- [engine/nlp/README.md](engine/nlp/README.md) — NLQ routing and execution
- [engine/reports/README.md](engine/reports/README.md) — Excel and chart output
- [engine/data/README.md](engine/data/README.md) — Market/ESG data and cache
- [engine/services/README.md](engine/services/README.md) — Enrichment orchestration and sessions
- [engine/schemas/README.md](engine/schemas/README.md) — Pydantic contract types
- [engine/tests/README.md](engine/tests/README.md) — pytest suite

## Desktop projects

See [desktop/README.md](desktop/README.md):

- [desktop/Riskbot.App/README.md](desktop/Riskbot.App/README.md) — main WPF application
- [desktop/Riskbot.Rtd/README.md](desktop/Riskbot.Rtd/README.md) — Excel-DNA RTD server
- [desktop/Riskbot.RtdBridge/README.md](desktop/Riskbot.RtdBridge/README.md) — shared RTD snapshot contract
- [desktop/Riskbot.App.Tests/README.md](desktop/Riskbot.App.Tests/README.md) — xUnit tests

## Solution entry points

| File | Purpose |
|------|---------|
| `engine/main.py` | FastAPI app, router registration, `.env` load |
| `desktop/Riskbot.sln` | Builds App, Rtd, RtdBridge, Tests |
| `desktop/Riskbot.App/App.xaml.cs` | DI composition root |
| `desktop/Riskbot.App/MainWindow.xaml` | Four-zone shell (blotter, treemap, NLQ, results) |
| `shared/openapi.yaml` | All `/health`, `/enrich`, `/nlq`, `/risk/*` contracts |
