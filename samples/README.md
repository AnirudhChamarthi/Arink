# `samples/` — example portfolio data

Demonstration inputs for first-run and documentation—not a runtime service.

## Contents

| Artifact | Purpose |
|----------|---------|
| [`SamplePortfolio.xlsx`](SamplePortfolio.xlsx) | Five US equities (AAPL, MSFT, JPM, XOM, NVDA) with risk limits |
| [`create_sample_portfolio.py`](create_sample_portfolio.py) | Regenerates the workbook from scratch |

## Why a Python generator script?

- **openpyxl** matches the engine’s report stack; one dependency story in [../engine/requirements.txt](../engine/requirements.txt).
- Regeneration is easy in CI or after schema changes to [`shared/portfolio_schema.json`](../shared/portfolio_schema.json).

The **desktop reads** the xlsx via C# Open XML ([`PortfolioFileManager`](../desktop/Riskbot.App/ExcelIntegration/PortfolioFileManager.cs))—Excel application not required.

## Sample portfolio design

| Metadata field | Typical value | Exercises |
|----------------|---------------|-----------|
| `VaRLimit` | 5% | Portfolio VaR breach styling |
| `MaxConcentration` | 15% | Single-name limit |
| `ExclusionFilters` | (optional) | Custom exclusions; try `ticker:XOM` via ESG preferences |

Holdings align with [`shared/portfolio_schema.json`](../shared/portfolio_schema.json) column names (`Ticker`, `AssetClass`, `Quantity`, …).

## Usage in the app

1. **File → Open Portfolio…** → select `samples/SamplePortfolio.xlsx`
2. Wait for enrich (network)
3. NLQ: “What is my parametric VaR?”
4. **Risk → ESG & Exclusion Preferences** to test exclusions on XOM

Regenerate:

```powershell
python samples\create_sample_portfolio.py
```

## Links

| Step | Doc |
|------|-----|
| Run instructions | [../RUN.md](../RUN.md) |
| File schema | [../shared/portfolio_schema.json](../shared/portfolio_schema.json) |
| Enrichment | [../engine/services/README.md](../engine/services/README.md) |

Parent: [../README.md](../README.md)
