# Contract requests from the web UI (`web/`)

Contract 2.0.0. Each item is worked around locally; none blocks the UI.

## 1. Add `currency` to `RunRecord`

**What.** `RunRecord.currency: str` (the dataset's `base_currency` / `currency`).

**Why.** Metrics with `unit = "currency"` should be shown with their currency (e.g. `$1,234,567`), but the run
page only has the `RunRecord`/`RunResult`, which do not carry it.

**Workaround.** The UI uses the currency of the dataset selected in the same browser session when the
dataset name matches; otherwise it shows a grouped number with no symbol and labels the column "currency".

```diff
 class RunRecord(_Model):
     ...
     dataset_name: str
+    currency: str = "USD"
     synthetic: bool
```

## 2. Export a JSON Schema and fixture for `AuditEvent` (and the health body)

**What.** Add `AuditEvent.json` to `generated/schema/` and an `audit_q*.json` fixture; optionally a
`Health` model for `GET /v2/health` (`{"status": "ok", "contract_version": ...}`).

**Why.** `GET /runs/{id}/audit` returns `list[AuditEvent]`, but no schema is generated, so the UI decoder
for it is the only one that cannot be checked mechanically against the contract.

**Workaround.** Decoder hand-written from `types.py` (`run_id, at, actor, event, detail`).

## 3. Richer fake comparison in the fixtures

**What.** Have `FakeComparator` (or the exported fixtures) fill `sensitivity`, `label_counts`, at least one
`flip`, one `break_even` (Q2) and one `method_spread` entry.

**Why.** All fixture comparisons have these empty, so the UI tests and mock mode cannot exercise the
sensitivity chart, flips or break-evens from contract data.

**Workaround.** Mock mode derives `sensitivity` and `label_counts` from the fixture variations using the
Comparator rules in CONTRACT.md 4.3 (`src/mocks/derive.ts`); tests build flips/break-evens by hand.

## 4. Optional progress counter on `RunRecord`

**What.** `RunRecord.n_completed: int = 0` (variations executed so far).

**Why.** The run page polls every 1.5 s; with only `status` it can show an indeterminate bar but not
"17 of 35 variations".

**Workaround.** Indeterminate progress bar plus elapsed time.

## 5. CORS for the preview port (minor)

The API allows `http://localhost:5173` (vite dev). `npm run preview` serves on `4173`; either allow it too
or document that the API's allowed origins are configurable.
