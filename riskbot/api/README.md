# Riskbot v2 REST API (`riskbot/api`)

A thin FastAPI adapter over the `RunService` port (CONTRACT.md 4.5 and 6.1). Each route parses its input
into contract types, enforces the HTTP-level limits, calls one `RunService` method and returns the
contract type it gets back. The app holds no state of its own.

```python
from riskbot.api import create_app

app = create_app(service)                                  # CORS: http://localhost:5173 and :4173
app = create_app(service, cors_origins=["https://ui.example"])
```

The composition root serves it: `python -m riskbot.app api` (default port 8000).
OpenAPI: `GET /v2/openapi.json`. Swagger UI: `/v2/docs`. ReDoc: `/v2/redoc`. Title "Riskbot v2 API",
version = `CONTRACT_VERSION`.

## Routes

| Method | Path | Body | Response | Status | RunService | Errors |
|---|---|---|---|---|---|---|
| GET | `/v2/health` | — | `{"status":"ok","contract_version":"2.0.0"}` | 200 | — | — |
| GET | `/v2/questions` | — | `list[QuestionInfo]` | 200 | `questions()` | — |
| GET | `/v2/models?question=` | — | `list[ModelSpec]` | 200 | `list_models(question)` | 422 |
| GET | `/v2/samples/{question}` | — | `Dataset` | 200 | `sample_dataset(question)` | 422 |
| POST | `/v2/datasets/validate` | `Dataset` | `list[DataQualityFinding]` | 200 | `validate(dataset)` | 413, 422 |
| POST | `/v2/calc` | `CalcRequest` | `ModelOutput` | 200 | `calc(request)` | 404, 413, 422 |
| POST | `/v2/runs` | `RunRequest` | `RunRecord` + `Location` header | **202** | `start_run(request, wait=False)` | 413, 422 |
| GET | `/v2/runs?limit=100` | — | `list[RunRecord]` (newest first, 1 <= limit <= 1000) | 200 | `list_runs(limit)` | 422 |
| GET | `/v2/runs/{run_id}` | — | `RunRecord` | 200 | `get_run` | 404 |
| GET | `/v2/runs/{run_id}/result` | — | `RunResult` | 200 | `get_result` | 404, 409 |
| GET | `/v2/runs/{run_id}/audit` | — | `list[AuditEvent]` | 200 | `audit_log` | 404 |
| POST | `/v2/runs/{run_id}/review` | `ReviewSubmission` | `RunRecord` | 200 | `submit_review` | 404, 409, 422 |
| GET | `/v2/runs/{run_id}/report?format=json\|md` | — | `Report`, or `text/markdown` for `md` | 200 | `get_report` | 404, 409, 422 |
| GET | `/v2/traces/{trace_id}` | — | `Trace` | 200 | `get_trace` | 404 |

`question` (path or query) must be a `QuestionId` value: `q1_market`, `q2_balance_sheet`, `q3_transition`;
anything else is 422. Dataset bodies are discriminated on `kind` (`market`, `balance_sheet`, `climate`).
Every route can also return 500.

## Error model

Every error response is a contract `ErrorBody`:

```json
{"code": "not_found", "message": "unknown run 'nope'", "details": {}}
```

| Cause | Status | `code` | `details` |
|---|---|---|---|
| `NotFound` from the service | 404 | `not_found` | from the exception |
| `Conflict` (e.g. result of a running run, review of an approved run) | 409 | `conflict` | from the exception |
| `ValidationFailed` from the service (bad params, plan for another question) | 422 | `validation_failed` | from the exception |
| Request validation (body, path, query, malformed JSON, unknown fields) | 422 | `validation_failed` | `{"errors": [{"loc", "msg", "type"}]}` |
| Body above 10 MB (checked on `Content-Length` and on streamed bytes) | 413 | `limit_exceeded` | `{"limit": "max_body_bytes", "value", "maximum"}` |
| Dataset or plan above `catalog.LIMITS` (checked before the service is called) | 413 | `limit_exceeded` | `{"limit": "<LIMITS key>", "value", "maximum"}` |
| Unknown route / wrong method | 404 / 405 | `not_found` / `validation_failed` | `{}` |
| Any other exception | 500 | `internal` | `{"request": "GET /v2/..."}` only; traceback logged to `riskbot.api` |

Validation error entries omit pydantic's `input` (it can be a whole dataset) and `ctx`.

Limits applied at the boundary (`limits.py`): market `positions <= max_positions` and
`dates <= max_history_days`; balance sheet assets + loan pools + deposits + wholesale lines + hedges
`<= max_balance_sheet_items`; climate `holdings <= max_holdings`; for `POST /v2/runs` with a plan, the
upper bound (product of grid dimension sizes + extras) `<= max_variations`.

CORS headers are added to every response, including 413 and 500, for allowed origins
(`Location` is exposed so the UI can follow a new run).

## curl examples

```bash
API=http://localhost:8000/v2

curl -s $API/health
curl -s $API/questions | jq '.[].question'
curl -s "$API/models?question=q1_market" | jq '.[].model_id'

# sample -> validate -> single calculation
curl -s $API/samples/q1_market > q1.json
curl -s -X POST $API/datasets/validate -H 'content-type: application/json' --data @q1.json
jq '{model_id: "q1.var", dataset: ., params: {method: "historical", window_days: 500}}' q1.json \
  | curl -s -X POST $API/calc -H 'content-type: application/json' --data @- | jq .metrics.var

# start a run with the default plan (202), poll, read the result
RUN=$(jq '{question: "q1_market", dataset: .}' q1.json \
  | curl -s -X POST $API/runs -H 'content-type: application/json' --data @- | jq -r .run_id)
curl -s $API/runs/$RUN | jq .status            # pending | running | awaiting_review | failed
curl -s $API/runs/$RUN/result | jq .comparison.metric_ranges.var
TRACE=$(curl -s $API/runs/$RUN/result | jq -r '.variations[0].output.metrics.var.trace_id')
curl -s $API/traces/$TRACE | jq '.steps[] | {id, formula, value}'

# review and sign off, then the report
curl -s -X POST $API/runs/$RUN/review -H 'content-type: application/json' \
  -d '{"decision":"approve","reviewer":"Ana","comment":"ok",
       "factor_edits":[{"factor_id":"history_length","likelihood":4,"reason":"short stress sample"}]}'
curl -s $API/runs/$RUN/report | jq .headline
curl -s "$API/runs/$RUN/report?format=md" > report.md
curl -s $API/runs/$RUN/audit | jq '.[].event'

# errors
curl -s $API/runs/nope                     # 404 {"code":"not_found",...}
curl -s $API/samples/q4                    # 422 {"code":"validation_failed","details":{"errors":[...]}}
```

## Layout

| File | Purpose |
|---|---|
| `__init__.py` | exports `create_app` |
| `app.py` | `create_app`, the `/v2` router, OpenAPI metadata, middleware wiring |
| `errors.py` | `ErrorBody` exception handlers and the 500 guard middleware |
| `limits.py` | 10 MB body limit middleware, `catalog.LIMITS` checks for datasets and plans |
| `tests/` | TestClient tests over `contract.fakes.FakeRunService` |

Tests: `python3 -m pytest riskbot/api` (offline, no server).

## Known limitations

- No authentication or rate limiting: the API is meant for a local or trusted network. Reviewer identity
  is whatever the client sends in `ReviewSubmission.reviewer`.
- The plan limit uses an upper bound before `applies_when` de-duplication; the planner applies the
  exact count. A plan whose bound exceeds 1000 but whose deduplicated size would not is rejected here.
- Request bodies are buffered in memory (up to 10 MB) before routing.
- 405 maps to `validation_failed` because `ErrorBody.code` has no method-not-allowed value.
