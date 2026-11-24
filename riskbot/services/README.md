# `riskbot.services`

The services layer sits between the pure models (`riskbot.core.*`) and orchestration. It plans
variation grids from the catalogue, runs the models, compares the results, verifies that every number
can be traced back to a calculation, stores runs in SQLite and writes the Markdown report.

The package imports only `riskbot.contract` and the standard library. It knows nothing about any
concrete model: everything model-specific comes from `contract.catalog`.

| Factory (exact export) | Class | Port (`contract/ports.py`) | Module |
|---|---|---|---|
| `registry()` | `InMemoryRegistry` | `ModelRegistry` | `registry.py` |
| `planner()` | `GridPlanner` | `VariationPlanner` | `planner.py` |
| `executor(registry)` | `ModelExecutor` | `VariationExecutor` (+ `execute_many`) | `executor.py` |
| `comparator()` | `StatisticalComparator` | `Comparator` | `comparator.py` |
| `verifier()` | `TraceNumberVerifier` | `NumberVerifier` | `verifier.py` |
| `sqlite_store(path)` | `SqliteRunStore` | `RunStore` | `store.py` |
| `reporter()` | `MarkdownReporter` | `Reporter` | `reporter.py` (+ `formatting.py`) |

## Registry

A dictionary keyed by `spec.model_id`, kept in insertion order and protected by a lock.

- Starts empty. `register` raises `ValidationFailed` for a duplicate id or for an object without a
  `ModelSpec` `spec` and a `run` method.
- `get` raises `NotFound` for an unknown id.
- `specs(question)` returns specs in registration order, filtered by question if one is given.

## Planner

`expand(plan, seed)` works like this:

1. Look up `plan.grid.model_id` and each extra's `model_id` in `catalog.MODEL_SPECS`, not in a registry,
   so a plan is checked against the contract whatever has been wired. An unknown id, a grid model from
   another question or an empty dimension raises `ValidationFailed`.
2. Walk the cartesian product of the dimensions with `itertools.product`, in the order the plan lists
   them (the last dimension changes fastest). Each combination goes through
   `resolve_params(spec, {**fixed, **combo})`. This fills in defaults, checks types, choices and ranges
   (`ValidationFailed` passes through) and drops parameters whose `applies_when` condition fails.
3. Compute `variation_id(model_id, effective_params)` and skip any combination whose effective
   parameters were already seen. The first occurrence wins.
4. Set `seed = derive_seed(run_seed, variation_id)`. The seed does not depend on execution order.
5. Raise `LimitExceeded` when the number of distinct grid variations is above
   `min(plan.max_variations, LIMITS["max_variations"])`. Before enumerating anything, a guard also
   rejects a raw product larger than 50 times the limit.
6. Append the extras the same way (`role="extra"`, duplicates removed). Extras do not count towards
   the grid limit.

`VariationSpec.params` holds the effective parameters, the same ones the model returns in
`ModelOutput.params`. The default plans give Q1 18 + 1 (covariance collapses for historical, fhs and
evt), Q2 32 + 3 and Q3 27 + 1. The tests check all three.

## Executor

`execute(spec, dataset)` looks up the model, runs it with the variation's params and seed, and runs
`conformance.check_output` against the catalogue spec. It falls back to the model's own spec for ids
outside the catalogue. The timing covers all of this and uses `time.perf_counter`.

- An exception of any kind, including `NotFound` for an unregistered model, becomes
  `error = "<ExceptionType>: <message>"` with `output=None`.
- Contract violations become `error = "ContractViolation: v1; v2; ..."`. The output is dropped, so a
  number that does not conform can never reach a comparison or a report.
- `execute_many(specs, dataset, max_workers=4)` runs the specs on a `ThreadPoolExecutor` and returns
  results in input order. Models are pure, so running them in parallel is safe.

## Comparator

The comparator uses successful variations only: `output` is present and `error` is empty. Grid
variations feed every section except break-evens, which come from extras.

| Field | Rule |
|---|---|
| `metric_ranges` | Every metric present in any successful grid output, in catalogue order. Gives min, `statistics.median`, max and n. |
| `method_spread` | Only when the spec has `method_param`. Takes the median per method value. If at least two of those medians are positive, the value is max / min of the positive ones. Otherwise the metric is left out. |
| `sensitivity` | For each grid dimension (in plan order) and each non-optional metric with `higher_is_worse` set: the median per dimension value, keyed by `str(effective value)` in the order first seen, and `effect = max - min`. A variation whose dimension was dropped by `applies_when` is skipped for that dimension. |
| `flips` | For the spec's `pass_label`. For each dimension, group grid variations by all *other* effective parameters. Every pair in a group whose outcomes differ (both `pass`/`fail`) gives one flip, from the earlier variation's value to the later one's. Ordered by dimension, then group, then pair. Duplicates are removed and the list is capped at 50, keeping the first ones. |
| `break_evens` | For each successful extra run: each `breakeven_*` metric gives `found=True` with its value, unit and trace id. Each *optional* `breakeven_*` metric that the spec declares but the output lacks gives `found=False, value=None`. The description names the extra's explicit parameters, for example `target=capital`. A failed extra run makes no claim. |
| `label_counts` | Per label, every allowed value from the catalogue, including zero counts, plus any other value seen. |

With no successful variations the comparator returns an empty `Comparison` and does not raise.

## Verifier

**`check_outputs`** checks every metric of every successful variation again: it must link to a trace
step that exists, and the step's value must equal the metric (`isclose`, rel 1e-9, abs 1e-12). Each
problem gives a `matched=False` finding at `variation:<id>/metric:<key>`.

**`verify_text(location, text, results)`** works in five steps:

1. **Mask identifiers.** Tokens that start with a letter or `_` and contain a digit are blanked,
   including chains joined by `. - : /`. Examples: `q1.var`, `v1a2b3c`, `run-0001`,
   `q2.reverse_stress-0a1b…`, `CET1`, `loss_p05`.
2. **Extract numbers.** A number may have a sign, which counts only when it is not glued to a word or
   number before it, so `1%-2%` reads as a range. It may have a currency marker (`$`, `US$`, `USD`),
   thousands separators and decimals. It may end in a suffix: `%`/`percent`/`pp`,
   `bp`/`bps`/`basis points`, `k`/`thousand`, `m`/`mn`/`million`, `b`/`bn`/`billion`,
   `tn`/`trillion` or `x`. A number glued to letters (`5th`, a hex hash) or inside a version string
   is not extracted.
3. **Ignore** unsigned plain integers 1–5 with no unit, currency or decimals (ratings), and plain
   integers 1900–2100 with no separators (years).
4. **Build candidates** from every metric of every successful variation, in each form its unit allows:
   - fractions and probabilities: raw, ×100 for `%`, ×10⁴ for `bp`
   - basis points: raw, /100 for `%`
   - ratios: raw, ×100 for `%`
   - currency and other absolute units: raw, and /10³, /10⁶, /10⁹, /10¹² for the scale suffixes

   A currency marker limits the candidates to currency metrics.
5. **Match** when `|printed − candidate| ≤ ½·10^(−decimals)` plus a 1e-9 relative epsilon. For
   example, `31.2%` matches 0.3118 and `31.3%` does not. A number with an explicit sign must match
   the sign. An unsigned number is compared by magnitude, because prose such as "falls by 1.2bn"
   describes a negative `delta_eve`.

The verifier returns one finding per extracted number. Its `value` is the number as printed (31.2
for "31.2%"), and its message names the matching metric, variation and trace, or explains the
mismatch. A Hypothesis property test checks that every value formatted by the reporter matches
itself.

## SQLite store

Tables: `runs(run_id, created_at, record, request)`, `results(run_id, json)`,
`traces(trace_id, run_id, json)`, `signoffs(run_id, json)` and
`audit(id AUTOINCREMENT, run_id, json)`. JSON is written with `model_dump_json` and read with
`model_validate_json`, so every value round-trips through the contract types exactly. The schema is
created on construction.

- **Thread safety:** one connection opened with `check_same_thread=False` and guarded by an `RLock`.
  Each write is a single `BEGIN IMMEDIATE` transaction. `":memory:"` therefore shares one database
  across threads. File databases use WAL.
- **Errors:** `create_run` on an existing id raises `Conflict`. The `get_*` methods and `update_run`
  raise `NotFound`, and so do `save_result` and `save_signoff` for an unknown run. `get_signoff`
  returns `None` when there is no sign-off. `append_audit` accepts any run id.
- **Ordering:** `list_runs` returns the newest first. `created_at` is normalised to UTC text, so
  mixed time zones sort correctly. `audit_log` returns the oldest first, by autoincrement id.
- **Traces:** `save_result` upserts the result and rebuilds the run's trace index, so saving again
  replaces the old index.

## Reporter

`build(result, signoff)` returns a `Report` whose `markdown` depends only on its inputs: no clock and
no randomness. The sections always appear in this order:

1. Title: the question title from `catalog.QUESTIONS`
2. Run metadata
3. Synthetic-data banner, when `run.synthetic`
4. Headline
5. Metric ranges (units formatted)
6. Method spread
7. Sensitivity
8. Conclusion flips
9. Break-evens
10. Label counts
11. Qualitative assessment, headed **Judgment** and marked "judgment, not calculation"
12. Overrides
13. Sign-off
14. Variations, including errors

Formats (`formatting.py`): fractions as `3.12%`, probabilities as `0.042`, basis points as `125 bp`,
currency with thousands separators (`1,234,568`), ratios as `1.35`, and emissions as `12,345.6 tCO2e`.

Headline sentences contain **only metric values from the run**:

- The minimum and maximum of the two main metrics. These are the first non-optional metrics with
  `higher_is_worse` set; non-currency metrics come first.
- Values of break-evens that were found.

Medians are never cited, because the median of an even number of values is an average that may
match nothing. Counts, spreads and effects are described in words. Every candidate sentence is then
checked with the verifier, and any sentence with a number that does not match is dropped. The tests
check that every headline number verifies, for all three default plans and for a hand-built Q2 run.

## Tests

```
python3 -m pytest riskbot/services
python3 -m pytest riskbot/contract/tests/test_architecture.py -k services
```

There are 120 tests, all offline, built on `contract.fakes` (FakeModel, FakeRegistry, fake_dataset)
and on hand-built results (`tests/helpers.py`).

## Limitations

- The verifier matches numbers, not meaning. "VaR is 31.2%" would match a 31.2% expected shortfall.
  Unsigned numbers are compared by magnitude, and the matching relies on rounding tolerance.
- Numbers glued to unknown letters (`10y`, `30d`) are ignored rather than flagged.
- Flips compare variations that differ in exactly one *effective* parameter. Pairs where one side has
  had a parameter dropped by `applies_when` are not compared.
- The store uses one serialised connection. That suits a single-process service but not heavy
  concurrent write loads.
