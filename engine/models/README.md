# `engine/models/` — risk and sustainability calculations

Pure **quantitative logic**: inputs are `EnrichedPortfolio` (+ parameters), outputs are Pydantic result types from [`schemas/contract.py`](../schemas/contract.py). Invoked by `api/routes/risk.py`, [`nlp/executor.py`](../nlp/executor.py), and [`reports/master_report.py`](../reports/master_report.py).

## Modules

| File | Responsibility | OpenAPI / NLQ surface |
|------|----------------|----------------------|
| [`var.py`](var.py) | Parametric, historical, Monte Carlo VaR | `/risk/var`, NLQ `var` |
| [`greeks.py`](greeks.py) | Black–Scholes + synthetic portfolio Greeks | `/risk/greeks`, NLQ `greeks` |
| [`garch.py`](garch.py) | GARCH(1,1), ARMA order selection (AIC/BIC) | `/risk/garch`, NLQ `garch` |
| [`stress.py`](stress.py) | Named + custom scenario P&L | `/risk/stress`, NLQ `stress`; reads [`shared/scenarios.json`](../../shared/scenarios.json) |
| [`sustainability.py`](sustainability.py) | ESG, carbon, Paris alignment, exclusions | `/risk/sustainability`, NLQ `sustainability` |
| [`exclusion_policy.py`](exclusion_policy.py) | Shared exclusion parsing (desktop mirrors rules in C#) | Used by sustainability + limits |
| [`portfolio_utils.py`](portfolio_utils.py) | Weights, notionals, concentration helpers | Internal |

## Why Python for models?

- **Vectorized returns** — VaR covariance, simulation draws (`numpy`).
- **ARCH/GARCH** — `arch` package for volatility forecasting; reproducing in C# would mean porting or native bindings.
- **Rapid model expansion** — Step 7 added four model families without touching WPF binaries.

**vs Julia:** Similar math, smaller package ecosystem for Excel report + FastAPI in one repo.

**vs Excel/VBA:** Not auditable at scale, no session API, poor test story.

## Data dependencies

Models assume enrich has populated:

- `returns_252d` (full session only — see `response_detail` on `/enrich`)
- `implied_vol`, `risk_free_rate`, `beta`, ESG/carbon fields

Session resolution: [`services/portfolio_resolve.py`](../services/portfolio_resolve.py) ← [`services/portfolio_session_store.py`](../services/portfolio_session_store.py).

## Desktop consumption

| Model output | UI |
|--------------|-----|
| `VarResult` | Result panel, treemap “VaR contribution” mode, limit monitor |
| `PortfolioGreeks` | RTD fields, documentation window |
| `StressResult` | Result panel + stress Excel attachment |
| `SustainabilityResult` | ESG treemap mode, breach rules |
| `GarchResult` | NLQ / full report |

C# does **not** reimplement these formulas; [`PortfolioRiskService`](../../desktop/Riskbot.App/Services/PortfolioRiskService.cs) caches API results on the session.

## Tests

[`tests/test_var.py`](../tests/test_var.py), [`test_step7.py`](../tests/test_step7.py), [`test_sustainability.py`](../tests/test_sustainability.py), [`test_exclusion_policy.py`](../tests/test_exclusion_policy.py) — fixed seeds where randomness applies.

Parent: [../README.md](../README.md)
