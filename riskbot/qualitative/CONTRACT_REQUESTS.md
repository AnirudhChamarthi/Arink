# Contract requests from `riskbot/qualitative`

None of these blocks the component. Each has a local workaround in place.

## 1. Standard governance keys for `BankBalanceSheet.governance`

**What:** document a recommended key set in `types.BankBalanceSheet.governance` (description) or CONTRACT.md
section 7: `cro_vacancy_months` (int), `board_risk_expertise` (bool), `risk_committee_meetings_per_year` (int),
`limit_breaches_last_year` (int), `independent_model_validation` (bool), `open_supervisory_findings` (int),
`hedges_reduced_last_year` (bool).

**Why:** the field is a free-form dict. The `risk_governance` and `hedging` rules can only read the keys they
know about, so a sample dataset that uses other names would leave `risk_governance` unassessed.

**Workaround:** the rubric recognises exactly these keys (README, Q2) and marks the factor unassessed when none
is present.

## 2. Evidence kinds for labels and comparison entries

**What:** extend `Evidence.kind` with `"label"` (ref `variation_id/label`) and `"comparison"` (ref is a path
such as `method_spread.var` or `label_counts.backtest_verdict`).

**Why:** several rules rely on categorical outputs (`backtest_verdict`, `basel_zone`, `verdict`, `quality`) and
on comparator results (method spread, label counts, flips, sensitivity). These have no dedicated kind today.

**Workaround:** `kind="note"` with structured refs `variation:<variation_id>/labels.<label>` and
`comparison.<path>`. Unassessed factors use `missing:<factor_id>`.

## 3. Make `ports.Assessor` `@runtime_checkable` (minor)

**Why:** this would let tests and the composition root `isinstance`-check implementations, as `ports.Model`
already allows.

**Workaround:** the tests compare method signatures with `inspect`.

## 4. Verifier note: digits inside identifiers

**What:** clarify in `ports.NumberVerifier.verify_text` whether digits inside identifiers (for example
`coverage_scope12`, `q3.transition`, ticker `ABC1`) are extracted as numbers.

**Workaround:** rationales never print identifiers that contain digits. They use the catalogue model title
or metric description, or a generic phrase.
