# Contract requests from `riskbot/services`

None of these block the work. Services currently uses the interpretation marked "current". Please
confirm it or change the contract.

## 1. `VerifierFinding.value`: printed number or normalised number?
- **What:** say in the field description whether `value` is the number as printed (31.2 for "31.2%")
  or the normalised value (0.312).
- **Current:** the number as printed, signed when a sign was printed.
- **Proposed diff (`types.py`):**
  `value: float | None = Field(description="The number as printed (e.g. 31.2 for '31.2%'); None if unparsable.")`

## 2. `ConclusionFlip`: which outcomes count?
- **What:** the Q1 `backtest_verdict` also has the value `n/a`. Should a change between `pass` and
  `n/a` count as a flip?
- **Current:** only `pass` <-> `fail` changes count as flips.
- **Proposed:** add to the docstring of `ModelSpec.pass_label`: "flips consider only pass/fail outcomes".

## 3. `RunStore.create_run` with an existing id
- **What:** `ports.RunStore` does not say what happens. `FakeStore` overwrites the run silently.
- **Current:** the SQLite store raises `Conflict`. It also raises `NotFound` from `save_result` and
  `save_signoff` when the run does not exist. `append_audit` accepts any run id.
- **Proposed:** add comments to `ports.RunStore`: `# Conflict if run_id exists` on `create_run` and
  `# NotFound if the run does not exist` on `save_result` and `save_signoff`. Bring `FakeStore` in line.

## 4. `VariationExecutor.execute_many`
- **What:** orchestration fans out variations. `execute_many(specs, dataset, max_workers)` is
  available on the services executor but is not part of the port.
- **Proposed:** add it to `ports.VariationExecutor` as an optional convenience, or leave fan-out to
  orchestration (LangGraph `Send`).
