# Riskbot v2 contract (version 2.0.1)

This document and the Python package `riskbot/contract/` together are the contract that links every
component. The code is authoritative where the two differ; report any difference as a contract issue.

## 1. Principles

1. **Single dependency direction.** Every component depends only on `riskbot.contract`. No component
   imports another. `riskbot/app.py` is the only composition root and wires concrete implementations.
   Enforced by `contract/tests/test_architecture.py`.
2. **Ports and adapters.** Interfaces are `typing.Protocol`s in `contract/ports.py`. Implementations
   satisfy them structurally; neighbours are replaced by `contract/fakes.py` in tests.
3. **One source of truth for data.** All boundary data is a Pydantic model in `contract/types.py`
   (unknown fields forbidden). JSON Schemas and example payloads for non-Python clients are generated
   (`python -m riskbot.contract.export` -> `contract/generated/`), never hand-written.
4. **The catalogue links the system.** `contract/catalog.py` declares every model id, parameter,
   metric key, unit and label. Core implements it; services plan from it; adapters and UI render it.
5. **Pure, deterministic math.** Core models have no I/O, network, clock or global state; the same
   (dataset, params, seed) always gives the same output, including trace ids.
6. **Every number is traceable.** Each metric links to a trace step whose value equals it
   (`conformance.check_output`). Language models never produce numbers.
7. **Judgment is labelled.** Qualitative ratings use `rules.rate`, cite evidence and record overrides.
8. **Fail loudly at boundaries.** Raise `contract.errors` types; adapters map them to HTTP/MCP errors.

## 2. Components, owners and deliverables

| Component | Package | Implements | Depends on (via contract) |
|---|---|---|---|
| Contract | `riskbot/contract` | everything shared | — |
| Market math (Q1) | `riskbot/core/market` | `Model` for `q1.var`, `q1.data_quality` | — |
| Balance-sheet math (Q2) | `riskbot/core/balance_sheet` | `Model` for `q2.resilience`, `q2.reverse_stress`, `q2.data_quality` | — |
| Climate math (Q3) | `riskbot/core/climate` | `Model` for `q3.transition`, `q3.data_quality` | — |
| Qualitative | `riskbot/qualitative` | `Assessor` | — |
| Services | `riskbot/services` | `ModelRegistry`, `VariationPlanner`, `VariationExecutor`, `Comparator`, `NumberVerifier`, `RunStore`, `Reporter` | `Model` |
| Orchestration | `riskbot/orchestration` | `RunService` (LangGraph), `RationaleDrafter` | all service ports, `Assessor` |
| REST API | `riskbot/api` | FastAPI app over `RunService` | `RunService` |
| MCP server | `riskbot/mcp_server` | MCP server over `RunService` | `RunService` |
| Web UI | `web/` | React app over the REST API | REST routes (section 6) |
| Composition root | `riskbot/app.py` | wiring | everything |

### Package entry points (exact names)

| Package | Must export |
|---|---|
| `riskbot.core.market` | `models() -> list[Model]`, `sample_dataset(seed: int = 0) -> MarketDataset` |
| `riskbot.core.balance_sheet` | `models() -> list[Model]`, `sample_dataset(seed: int = 0) -> BankBalanceSheet` |
| `riskbot.core.climate` | `models() -> list[Model]`, `sample_dataset(seed: int = 0) -> ClimatePortfolio` |
| `riskbot.qualitative` | `assessor() -> Assessor` |
| `riskbot.services` | `registry() -> ModelRegistry`, `planner() -> VariationPlanner`, `executor(registry) -> VariationExecutor`, `comparator() -> Comparator`, `verifier() -> NumberVerifier`, `sqlite_store(path: str) -> RunStore` (`":memory:"` allowed), `reporter() -> Reporter` |
| `riskbot.orchestration` | `run_service(*, registry, planner, executor, comparator, verifier, store, reporter, assessor, samples: dict[QuestionId, Callable[[], Dataset]], drafter=None, checkpoint_path: str = ":memory:") -> RunService` |
| `riskbot.api` | `create_app(service: RunService) -> fastapi.FastAPI` |
| `riskbot.mcp_server` | `create_server(service: RunService) -> mcp.server.mcpserver.MCPServer` |

## 3. Conventions

- **Signs.** Losses are positive numbers in loss metrics (VaR, ES, credit_loss, loss_pct...). Quantities are
  signed (negative = short). `delta_*` metrics are signed changes (negative = worse for equity).
- **Units.** Every metric carries a `Unit`; fractions are decimals (0.07 = 7%); basis points are `bp`.
- **Weights.** Market weights are signed market value / gross exposure (sum of |MV|). Cash has price 1
  per unit and no return series (zero returns).
- **Ids and hashes.** Use `contract.hashing` only: trace ids `'<model_id>-<12 hex>'` (+ `-suffix` when a
  model emits several traces), variation ids `'v' + 10 hex`, per-variation seeds via `derive_seed`.
- **Parameters.** Models call `conformance.resolve_params(spec, params)` first and return the effective
  parameters in `ModelOutput.params`.
- **Traces.** Built with `contract.tracing.TraceBuilder`; LaTeX in `formula`; the numbers substituted in
  `substitution`; assumptions listed; any data problem also emitted as a `DataQualityFinding`.
- **Randomness.** Only `numpy.random.default_rng(seed)` from the given seed.
- **Time.** Store datetimes in UTC, timezone-aware.
- **Errors.** `ValidationFailed` (bad input), `NotFound`, `Conflict` (wrong state), `LimitExceeded`
  (`catalog.LIMITS`). Never let a raw exception cross a component boundary from an adapter.

## 4. Behaviour of each component (acceptance criteria)

### 4.1 Core math (market, balance_sheet, climate)
- Implements every model of its question in `catalog.MODEL_SPECS` exactly: ids, parameters, metric keys,
  units and labels, so that `conformance.check_output(spec, output) == []` for the sample dataset and every
  value combination of the default plan.
- `sample_dataset()` returns a deterministic synthetic dataset (`synthetic=True`) designed to make the
  question interesting (see section 7) and within `catalog.LIMITS`.
- Each formula has at least one independent test oracle (closed form, recovery of known parameters from
  simulated data, published value, or a property such as ES >= VaR, monotonicity in shock size).
- No imports outside the contract, numpy, scipy, pandas, arch and the standard library (no I/O).
- A `README.md` in the package documents every formula, assumption and limitation (model documentation).

### 4.2 Qualitative
- One rubric per question (factors listed in section 8), each factor with a deterministic pre-fill rule
  where data allows (`source="rule"`, evidence citing metric keys / findings / dataset fields) or
  `source="unassessed"` with likelihood=impact=3, control=adequate.
- Ratings via `rules.rate`; overall via `rules.overall_rating`; `apply_edits` logs every change.
- Works from `VariationResult`s and `Comparison` only (no model calls). Tested with fakes.

### 4.3 Services
- `registry()` starts empty; `register` rejects duplicate model ids (`ValidationFailed`).
- Planner as specified in `ports.VariationPlanner`, using `resolve_params` for each combination (so
  inapplicable parameters disappear and duplicates collapse) and `catalog.LIMITS["max_variations"]`.
- Executor runs the model, times it, applies `check_output`; any exception or violation becomes
  `VariationResult.error` (message starting with the exception type).
- Comparator: `metric_ranges` over successful grid variations for every metric present; `method_spread`
  (max/min, positive values only) across the spec's `method_param` values using the median per method;
  `sensitivity` for every grid dimension and every non-optional metric with `higher_is_worse` set;
  `flips` for the spec's `pass_label`: for each dimension, pairs of variations differing only in that
  dimension whose label differs; `break_evens` from extra-run metrics starting with `breakeven_`
  (found = present; a missing optional breakeven metric of an extra run gives found=False);
  `label_counts` for every label of grid variations.
- Verifier as specified in `ports.NumberVerifier`.
- `sqlite_store(path)`: SQLite, JSON columns from Pydantic, thread-safe (one connection per call or a lock),
  `":memory:"` for tests; schema created on first use.
- Reporter: deterministic Markdown; headline sentences use only numbers taken from `Comparison`/metrics
  (formatted so the verifier can match them) and state that sample data is synthetic when it is.

### 4.4 Orchestration
- LangGraph `StateGraph` per run: `validate -> plan -> execute (fan-out) -> check_outputs -> compare ->
  assess -> [draft_rationales if use_llm] -> verify_text -> await_review (interrupt)`; review resumes the
  graph: `apply_edits -> signoff -> report`. Checkpointer: `SqliteSaver` at `checkpoint_path`.
- `start_run(wait=False)` executes in a background thread; `wait=True` blocks until `awaiting_review`
  or `failed`. Status transitions as in `ports.RunService`; each transition appended to the audit log.
- `calc` runs a single model synchronously; `validate` runs pydantic validation plus the question's
  `*.data_quality` model and returns its findings.
- Enforces `catalog.LIMITS`; maps internal errors to contract errors; a failing variation does not fail
  the run, but a run with zero successful grid variations is `failed`.
- `drafter=None` means no LLM. Drafted rationales pass `verify_text`; unmatched numbers cause the draft to
  be rejected for that factor (rule rationale kept) and a `VerifierFinding` recorded.
- Tests run entirely on `contract.fakes` (fake registry, store, etc.).

### 4.5 REST API (`riskbot/api`)
Routes in section 6; JSON bodies are the contract types; errors are `ErrorBody` with the status from the
exception class (`http_status`). OpenAPI generated by FastAPI; `GET /v2/openapi.json`. CORS allows
`http://localhost:5173` (web dev server). Tests use `FakeRunService` and FastAPI's TestClient.

### 4.6 MCP server (`riskbot/mcp_server`)
Tools, resources and prompts in section 6.2, all over `RunService`. Read-only tools annotated
`readOnlyHint=True`; `start_run` is the only state-changing tool. No review/sign-off tool. Tool errors
use the contract error message. Tests use `FakeRunService` and the in-process MCP client.

### 4.7 Web UI (`web/`)
React + TypeScript + Vite. Types generated from `contract/generated/schema` (or hand-written to match
them exactly, checked by a test against the fixtures). Screens: datasets/samples and validation, new run
(plan shown from the question's default and editable within catalogue choices), run status, variation
comparison (table + range/sensitivity charts), trace viewer (KaTeX), qualitative assessment with edits,
review/sign-off, report. Synthetic-data banner whenever `synthetic` is true; every metric links to its
trace step. Talks only to the REST API (base URL configurable); tests run against the fixtures.

## 5. Statuses and run lifecycle

`pending -> running -> awaiting_review -> approved | rejected`; any state -> `failed` on an unrecoverable
error. `get_result` / `get_report` raise `Conflict` for `pending`, `running` and `failed`. `submit_review`
raises `Conflict` unless `awaiting_review`.

## 6. External interfaces

### 6.1 REST (prefix `/v2`)

| Method | Path | Body | Response | RunService |
|---|---|---|---|---|
| GET | `/v2/health` | — | `{"status":"ok","contract_version":...}` | — |
| GET | `/v2/questions` | — | `list[QuestionInfo]` | `questions` |
| GET | `/v2/models?question=` | — | `list[ModelSpec]` | `list_models` |
| GET | `/v2/samples/{question}` | — | `Dataset` | `sample_dataset` |
| POST | `/v2/datasets/validate` | `Dataset` | `list[DataQualityFinding]` | `validate` |
| POST | `/v2/calc` | `CalcRequest` | `ModelOutput` | `calc` |
| POST | `/v2/runs` | `RunRequest` | `RunRecord` (202) | `start_run(wait=False)` |
| GET | `/v2/runs?limit=` | — | `list[RunRecord]` | `list_runs` |
| GET | `/v2/runs/{run_id}` | — | `RunRecord` | `get_run` |
| GET | `/v2/runs/{run_id}/result` | — | `RunResult` | `get_result` |
| GET | `/v2/runs/{run_id}/audit` | — | `list[AuditEvent]` | `audit_log` |
| POST | `/v2/runs/{run_id}/review` | `ReviewSubmission` | `RunRecord` | `submit_review` |
| GET | `/v2/runs/{run_id}/report` | — | `Report`; `?format=md` -> `text/markdown` | `get_report` |
| GET | `/v2/traces/{trace_id}` | — | `Trace` | `get_trace` |

### 6.2 MCP

| Kind | Name | Maps to |
|---|---|---|
| tool | `list_questions` | `questions` |
| tool | `list_models(question?)` | `list_models` |
| tool | `get_sample_dataset(question)` | `sample_dataset` |
| tool | `validate_dataset(dataset)` | `validate` |
| tool | `calculate(model_id, dataset, params?, seed?)` | `calc` |
| tool | `start_run(question, dataset, plan?, seed?, wait?)` | `start_run` |
| tool | `run_status(run_id)` | `get_run` |
| tool | `run_result(run_id)` | `get_result` |
| tool | `get_trace(trace_id)` | `get_trace` |
| tool | `get_report(run_id)` | `get_report` |
| resource | `riskbot://models` | `list_models` (JSON) |
| resource | `riskbot://traces/{trace_id}` | `get_trace` (Markdown rendering of the trace) |
| resource | `riskbot://reports/{run_id}` | `get_report().markdown` |
| prompt | `assess_market_risk`, `assess_balance_sheet`, `assess_transition_risk` | guidance: run the question, quote only tool numbers |

## 7. Sample datasets (designed behaviour)

- **Q1 market**: 12-15 positions incl. at least 2 shorts and 1 cash line; ~780 trading days of GARCH
  returns with fat tails and a ~60-day stress episode inside the oldest 500 days, so the 250-day and
  750-day windows differ clearly; a few missing values and one stale series for data-quality findings.
- **Q2 bank**: ~10bn balance sheet, ~25% long-dated securities (about half HTM), loans in 4 pools, deposits
  ~70% of funding with one concentrated, mostly uninsured segment, a wholesale line, thin hedging; designed
  so the base case passes while +300 bp with a fast run fails; governance fields filled.
- **Q3 climate**: ~20 issuers across >= 8 sectors (including energy, utilities, materials, technology);
  ~30% missing scope 1-2, most missing scope 3, mixed data quality, one stale year, a few controversy flags.

## 8. Qualitative rubrics (factor ids)

- **Q1**: `method_spread`, `backtest_performance`, `history_length`, `data_quality`, `concentration`,
  `short_exposure`, `normality_reliance`.
- **Q2**: `uninsured_deposits`, `deposit_concentration`, `duration_gap`, `hedging`, `htm_reliance`,
  `wholesale_dependence`, `risk_governance`, `credit_concentration`.
- **Q3**: `emissions_coverage`, `estimated_emissions`, `scope3_coverage`, `stale_data`, `controversies`,
  `exclusion_breaches`, `high_emitting_concentration`, `scenario_dispersion`.

## 9. Change process

The contract is frozen while components are built. A component that needs a change writes it to
`CONTRACT_REQUESTS.md` in its own package (what, why, proposed diff) and works around it locally; the
integrator decides, bumps `CONTRACT_VERSION`, regenerates `contract/generated/` and records it below.

## 10. Definition of done (every Python component)

- `python -m pytest riskbot/<package>` passes offline; the architecture test passes.
- Public functions typed; module and function docstrings explain the maths or behaviour.
- No new third-party dependency beyond `pyproject.toml` without a contract request.

## Changelog
- 2.0.0 (2026-11-24): initial contract.
- 2.0.1 (2026-11-24): q1.data_quality outlier rule changed from a global raw-MAD threshold (flagged ~200 genuine
  stress-period returns on the sample) to 10 robust sigmas around a centred 63-day rolling median (requested by the
  market component).
