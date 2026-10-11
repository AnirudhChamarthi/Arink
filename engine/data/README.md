# `engine/data/` — market, ESG, and cache

**I/O and caching** for enrichment—not portfolio models. Keeps `services/enrich.py` readable.

## Modules

| File | Role |
|------|------|
| [`market.py`](market.py) | Prices, 252-day returns, implied vol, risk-free rate (yfinance, FRED-style sources) |
| [`esg.py`](esg.py) | ESG scores, carbon intensity proxies |
| [`cache.py`](cache.py) | `diskcache` with ~4h TTL to respect free API rate limits |

## Why Python for data ingestion?

- **yfinance** and HTTP ecosystems are Python-first for research prototypes.
- Scriptable retries/timeouts without recompiling the desktop app when a provider changes.

**vs C# for fetch:** Would work, but enrichment logic would split across processes with heavier serialization of full return series on every refresh.

**vs commercial data vendors only:** This repo targets demonstrable free APIs; Python glue is fastest to maintain.

## Call chain

```
api/routes/enrich.py
  → services/enrich.py
    → data/market.py, data/esg.py
    → data/cache.py (per-ticker keys)
  → portfolio_session_store (full enriched book)
```

Desktop [`EnrichmentService`](../../desktop/Riskbot.App/Services/EnrichmentService.cs) only sees **display** fields from `/enrich?response_detail=display`; full returns stay server-side for VaR/GARCH.

## Operational notes

- Enrichment needs **network** access; failures surface as `EnrichmentFailedEvent` on the bus.
- **View → Refresh Market Data** re-triggers the same pipeline.

Parent: [../README.md](../README.md)
