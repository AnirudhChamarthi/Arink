# How to run Riskbot

Riskbot is a **WPF desktop app** plus a **local Python engine** on `http://127.0.0.1:8765`. The app can start the engine for you.

## Prerequisites

| Tool | Notes |
|------|--------|
| **.NET 8 SDK** | [Download](https://dotnet.microsoft.com/download) — Windows desktop |
| **Python 3.11+** | On PATH as `python` (or set `RISKBOT_PYTHON` to your interpreter) |
| **Optional** | `ANTHROPIC_API_KEY` in repo `.env` for full NLQ (Claude routing) |

## 1. One-time setup

```powershell
git clone <repository-url> SustainableC
cd SustainableC

# Python engine (a virtual environment is recommended)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r engine\requirements.txt

# Optional: API key for NLQ
copy .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
# (or set it in the app under Help → API Key Settings)

# Sample portfolio (or use the pre-generated file under samples/)
python samples\create_sample_portfolio.py
```

## 2. Run the desktop app (recommended)

```powershell
cd desktop
dotnet run --project Riskbot.App\Riskbot.App.csproj
```

- The app spawns the engine automatically and waits for `/health`. It uses `python` from PATH, so launch it from the shell where your virtual environment is active, or set `RISKBOT_PYTHON` in `.env` to the full interpreter path (e.g. `.venv\Scripts\python.exe`).
- Status bar shows **Engine: online** when ready.
- **File → Open Portfolio…** → choose `samples\SamplePortfolio.xlsx`.
- Wait for enrichment (blotter fills in; cells may flash).
- Try **NLQ** (“What is my parametric VaR?”) or **Risk → Run Full Risk Report**.

Build release binary:

```powershell
dotnet build desktop\Riskbot.sln -c Release
# Run: desktop\Riskbot.App\bin\Release\net8.0-windows\Riskbot.App.exe
```

## 3. Run the engine alone (optional / debugging)

```powershell
cd engine
python -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Health check:

```powershell
curl http://127.0.0.1:8765/health
```

Then start the desktop app in another terminal (it will attach to the already-running engine).

## 4. Tests

```powershell
cd engine
python -m pytest -q

cd ..\desktop
dotnet build Riskbot.App\Riskbot.App.csproj
dotnet test Riskbot.App.Tests\Riskbot.App.Tests.csproj
```

## 5. Excel RTD add-in (optional)

See [desktop/Riskbot.Rtd/README.md](desktop/Riskbot.Rtd/README.md). Requires Excel + the registered `Riskbot.Rtd` add-in; the desktop app must be running with an enriched portfolio.

## Sample portfolio

**`samples/SamplePortfolio.xlsx`** — five US equities (AAPL, MSFT, JPM, XOM, NVDA) with VaR limit 5% and max concentration 15%. Use **Risk → ESG & Exclusion Preferences** (e.g. `ticker:XOM`) to test custom exclusions.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Crash opening `.xlsx` | Check the file has `Holdings` and `Metadata` sheets (see `shared/portfolio_schema.json`), or start from **File → New Portfolio** |
| Engine: engine/ folder not found | Run from a cloned repo; the app locates `engine/` by searching upward from its own folder, so a copied EXE on its own will not work |
| Engine timeout | Port 8765 in use — stop the other process, or run the engine manually (section 3) |
| Engine fails to start / missing modules | The `python` on PATH is not the one you installed requirements into; set `RISKBOT_PYTHON` in `.env` |
| Enrichment slow / fails | Needs network (yfinance, etc.); retry **View → Refresh Market Data** |
| NLQ uses keywords only | Add `ANTHROPIC_API_KEY` in **Help → API Key Settings** (writes `.env`, restarts engine) |
