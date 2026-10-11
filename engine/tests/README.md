# `engine/tests/` — pytest suite

Validates models, routes, NLQ, reports, and security constraints (Step 11). **Python tests belong here** because they execute against the same modules Uvicorn loads—no WPF harness required.

## Layout

| Pattern | Examples |
|---------|----------|
| Unit (models) | `test_var.py`, `test_sustainability.py`, `test_exclusion_policy.py` |
| HTTP integration | `test_nlq.py`, `test_step7.py`, `test_step9.py` via `httpx.AsyncClient` |
| Snapshots / Excel | `test_step9.py`, `test_step11.py` |
| Security | `test_step9_security.py`, `test_step11_security.py` |

Shared fixtures: [`conftest.py`](conftest.py).

## Why pytest?

- **Parametrize** VaR methods and stress scenarios.
- **`httpx`** async tests against FastAPI app instance—closer to production than mocking every model.
- **Fixed RNG seeds** for Monte Carlo reproducibility.

**vs C# tests for engine:** Would require hosting Python or duplicating math—avoided by boundary at OpenAPI.

## Run

```powershell
cd engine
python -m pytest -q
```

Desktop tests: [`desktop/Riskbot.App.Tests/README.md`](../../desktop/Riskbot.App.Tests/README.md).

Parent: [../README.md](../README.md)
