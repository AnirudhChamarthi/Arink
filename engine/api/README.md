# `engine/api/` — HTTP surface (FastAPI routers)

Thin **transport layer**: validate bodies with Pydantic, call services/models, map errors to HTTP status codes. No business formulas here.

## Structure

```
api/
├── __init__.py
└── routes/
    ├── health.py    # GET /health
    ├── enrich.py    # POST /enrich
    ├── nlq.py       # POST /nlq
    └── risk.py      # POST /risk/var, /greeks, /stress, /sustainability, /garch, /full-report
```

Registered in [`main.py`](../main.py):

```python
app.include_router(health.router)
app.include_router(enrich.router)
app.include_router(nlq.router)
app.include_router(risk.router)
```

## Why FastAPI (Python) for HTTP?

| Alternative | Why not primary here |
|-------------|----------------------|
| Flask | Fewer automatic OpenAPI/schema hooks |
| ASP.NET Minimal API in C# | Would colocate UI and quant; harder numpy/arch interop |
| gRPC | Overkill for localhost JSON; worse curl/debug story |

FastAPI + Pydantic gives **typed handlers** that stay aligned with [`schemas/contract.py`](../schemas/contract.py) and [`shared/openapi.yaml`](../../shared/openapi.yaml).

## Route → implementation map

| Route file | Endpoint | Delegates to |
|------------|----------|--------------|
| `health.py` | `GET /health` | Inline `{status: ok}` |
| `enrich.py` | `POST /enrich` | [`services/enrich.py`](../services/enrich.py) |
| `nlq.py` | `POST /nlq` | [`nlp/executor.py`](../nlp/executor.py) |
| `risk.py` | `POST /risk/var` | [`models/var.py`](../models/var.py) |
| `risk.py` | `POST /risk/greeks` | [`models/greeks.py`](../models/greeks.py) |
| `risk.py` | `POST /risk/stress` | [`models/stress.py`](../models/stress.py) + [`reports/stress_report.py`](../reports/stress_report.py) |
| `risk.py` | `POST /risk/sustainability` | [`models/sustainability.py`](../models/sustainability.py) |
| `risk.py` | `POST /risk/garch` | [`models/garch.py`](../models/garch.py) |
| `risk.py` | `POST /risk/full-report` | [`reports/master_report.py`](../reports/master_report.py) |

`risk.py` uses [`services/portfolio_resolve.py`](../services/portfolio_resolve.py) to turn `portfolio_session_id` into an `EnrichedPortfolio`.

## Desktop client mirror

[`desktop/Riskbot.App/ApiClient/RiskbotApiClient.cs`](../../desktop/Riskbot.App/ApiClient/RiskbotApiClient.cs) — method names match routes (`EnrichAsync`, `RunVarAsync`, `RunNlqAsync`, etc.).

## Error contract

`ValueError` from services/models → **422** with `detail` string. Keeps desktop able to show engine validation messages (sanitized in `NlqErrorSanitizer` on the client).

Parent: [../README.md](../README.md)
