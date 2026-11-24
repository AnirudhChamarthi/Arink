# `riskbot.qualitative`: rubric-based qualitative assessment

> **These ratings are judgment, not measurement.** The rules below encode one analyst's documented
> conventions so that the pre-fill is transparent, repeatable and challengeable. They are not calibrated
> probabilities. Every factor can be overridden by a reviewer, and every override is logged.

Entry point: `riskbot.qualitative.assessor() -> Assessor` (implements `contract.ports.Assessor`).

## How a rating is formed

1. **Rubrics are data.** `rubrics.RUBRICS` maps each question to a tuple of `FactorDef` rows: `factor_id`,
   name, description, default impact, rule function, the inputs it reads, the basis for the control
   rating, and the rule's thresholds (`params`). The thresholds in this README are the same numbers as in
   `q1.py`, `q2.py` and `q3.py`.
2. **Rules are deterministic.** Each rule reads only the dataset (contract types), the `VariationResult`
   outputs (metric keys and labels from `contract/catalog.py`), data-quality findings and the `Comparison`.
   It returns likelihood (1-5), impact (1-5), control strength (weak / adequate / strong), a rationale
   and evidence. It never calls a model.
3. **Ratings use the shared rules** (`contract.rules`): inherent = likelihood x impact (1-4 low, 5-9
   medium, 10-15 high, 16-25 critical); residual lowers it one level for adequate and two for strong
   controls; the overall rating is the worst residual.
4. **Missing inputs are explicit.** If a rule's required input is missing (e.g. a model failed or a
   governance field is absent), the factor is `source="unassessed"`, likelihood = impact = 3, control
   adequate, and the rationale names what was missing. Unassessed factors need analyst review.

**Banding.** "Higher is worse" thresholds `(a, b, c, d)` give likelihood 1 below `a`, 2 from `a`, 3 from
`b`, 4 from `c`, 5 from `d` (lower bounds inclusive). "Lower is worse" thresholds are read downwards: 1 at
or above `a`, 5 below `d`.

**Evidence references.**

| `kind` | `ref` | Example |
|---|---|---|
| `metric` | metric key | `uninsured_deposit_share` |
| `trace` | `trace_id/step` behind that metric | `q2.data_quality-1a2b3c4d5e6f/uninsured_deposit_share` |
| `finding` | finding `check` | `missing_returns` |
| `dataset_field` | path into the dataset | `positions[3].quantity`, `governance.cro_vacancy_months` |
| `note` | `comparison.<path>`, `variation:<variation_id>/labels.<label>` or `missing:<factor_id>` | `comparison.method_spread.var` |

**Numbers in rationales.** Rationales print only metric values, formatted exactly as the number
verifier expects (fractions as percent with one decimal, `0.312 -> "31.2%"`; counts and days as integers;
years with one decimal; ratios with two decimals). Shares computed from the dataset, counts of variations
and comparison ratios are described in words ("about a third", "six methods") so that no unverifiable
digit appears. Labels containing digits (tickers, segment names) are replaced by a generic phrase. A test
checks every rationale of every scenario against this rule.

**Analyst edits** (`apply_edits`). All edits are validated first (unknown factor id, blank reviewer or a
naive timestamp raise `ValidationFailed`, and nothing changes). Edits are then applied in order to a copy:
each field whose value actually changes produces one `Override(factor_id, field, old, new, reason, by,
at)`; the factor's ratings are recomputed with `rules.rate` and its source becomes `analyst`; the overall
rating is recomputed. An edit that changes nothing is not logged and leaves the source unchanged. The
input assessment is never mutated.

---

## Q1: market tail risk ("how far should we trust the VaR number?")

| Factor | Measures | Rule (likelihood) | Impact | Control | Why it matters |
|---|---|---|---|---|---|
| `method_spread` | Model risk: dependence of VaR on the method. | `comparison.method_spread["var"]` (max/min of per-method median VaR), or computed from the grid if absent: < 1.25 -> 1, 1.25 -> 2, 1.5 -> 3, **2.0 -> 4**, 3.0 -> 5. Rationale quotes the lowest and highest median-ranked VaR and their methods. | 4 | Benchmarking (effective challenge, SR 11-7): strong with all six methods, adequate with >= 3, weak otherwise. | If the number halves or doubles with a modelling choice, a limit set on it is arbitrary. JPMorgan's 2012 "London Whale" loss followed a VaR model change that roughly halved reported VaR. |
| `backtest_performance` | Whether forecasts are exceeded as often as they should be. | Fail share of `backtest_verdict` (pass/fail only; `n/a` ignored) from `comparison.label_counts`: 0 -> 1, > 0 -> 2, 25% -> 3, 50% -> 4, 75% -> 5. Any `basel_zone` red raises likelihood to at least 4, yellow to at least 3. Quotes the largest `backtest_exceptions`. Unassessed if no pass/fail verdicts. | 4 | Backtesting is itself the control (adequate). | The Basel traffic light (green 0-4, yellow 5-9, red 10+ exceptions in 250 days at 99%) exists because VaR models failed silently. In 2008 many banks recorded far more exceptions than their models allowed. |
| `history_length` | Whether the history is long enough to estimate tails and include stress. | `q1.data_quality.history_days`: >= 1250 -> 1, < 1250 -> 2, < 750 -> 3, < 500 -> 4, < 250 -> 5. +1 if `comparison.sensitivity` shows the window changes median VaR by >= 25%. | 3 | Weak if the history cannot fill the 750-day window, else adequate. | LTCM (1998) calibrated on a few calm years and lost about USD 4.6bn in weeks. UBS's 2008 report on its subprime losses criticised reliance on VaR built on benign history, and regulators then added stressed VaR (Basel 2.5). |
| `data_quality` | Missing, stale and outlying data. | `q1.data_quality` label: good -> 1, fair -> 3, poor -> 4; +1 if any finding has severity error; at least 2 if any warning. Quotes `missing_share`, `stale_series`, `outlier_count`; cites each finding check. | 3 | Automated checks; weak if rated poor. | Stale prices understate volatility and correlation. BCBS 239 (2013) on risk data aggregation followed banks' inability to aggregate exposures in 2008. |
| `concentration` | Dependence on the largest non-cash position. | Largest \|weight\| = \|MV\| / gross exposure (cash excluded from the max, included in gross): < 10% -> 1, 10% -> 2, 20% -> 3, 30% -> 4, 50% -> 5. Effective number of positions (1/HHI) is described in words. | 3 | No limit data: adequate. | Concentrated positions break the diversification that VaR assumes: Archegos (2021) cost its prime brokers more than USD 10bn, Credit Suisse alone about USD 5.5bn. |
| `short_exposure` | Short share of gross exposure. | Short MV / gross: none -> 1, any -> 2, 10% -> 3, 25% -> 4, 40% -> 5. | 3 | No borrow or stop-loss data: adequate. | Short losses are unbounded and exposed to squeezes and borrow recalls: Melvin Capital needed a USD 2.75bn rescue in the January 2021 GameStop squeeze. |
| `normality_reliance` | How much a Gaussian VaR understates fat-tailed estimates. | Ratio of the highest fat-tailed (evt, student_t) median-ranked VaR to the normal one: < 1.1 -> 1, 1.1 -> 2, 1.25 -> 3, 1.5 -> 4, 2.0 -> 5. | 4 | Weak if any normal-method backtest fails; adequate otherwise. | "We were seeing things that were 25-standard deviation moves, several days in a row" (Goldman Sachs CFO, August 2007): Gaussian tails make crises look impossible. FRTB moved the market-risk capital measure from VaR to 97.5% expected shortfall for this reason. |

## Q2: balance-sheet resilience ("could it survive a rate shock plus a deposit run?")

| Factor | Measures | Rule (likelihood) | Impact | Control | Why it matters |
|---|---|---|---|---|---|
| `uninsured_deposits` | Run-prone funding. | `q2.data_quality.uninsured_deposit_share`: < 20% -> 1, 20% -> 2, 35% -> 3, 50% -> 4, 70% -> 5. | 4; 5 if any fast-run grid variation fails on liquidity (`binding_constraint` liquidity or both). | HQLA share of assets: strong >= 20%, adequate >= 10%, weak below. | Silicon Valley Bank (March 2023): over 90% of deposits uninsured, USD 42bn withdrawn in one day. |
| `deposit_concentration` | Dependence on one depositor group. | `largest_segment_share`: < 15% -> 1, 15% -> 2, 25% -> 3, 40% -> 4, 60% -> 5. Names the segment from the dataset. | 4 | Insured share of the largest segment: strong >= 75%, adequate >= 40%, weak below. | SVB's deposits came largely from one connected venture-capital and tech network, which ran together. |
| `duration_gap` | Interest-rate risk in the banking book (EVE). | \|`duration_gap_years`\|: < 1 -> 1, 1 -> 2, 2 -> 3, 3 -> 4, 5 -> 5. | From the worst (most negative) `delta_eve_pct_cet1` in the grid: loss < 5% -> 1, 5% -> 2, 10% -> 3, 15% -> 4 (the Basel IRRBB supervisory outlier test level), 30% -> 5; default 4 if absent. | Hedge ratio: strong >= 50%, adequate >= 20%, weak below. | The US savings-and-loan crisis and SVB were both long fixed-rate assets funded by short deposits. At end-2022 SVB's unrealised securities losses were close to its equity. |
| `hedging` | Swap coverage of fixed-rate securities. | `hedge_ratio` (lower is worse): >= 50% -> 1, < 50% -> 2, < 30% -> 3, < 15% -> 4, < 5% -> 5. | 4; 2 if \|duration gap\| < 2 years. | `governance.hedges_reduced_last_year`: true -> weak; false or not reported -> adequate. | SVB removed most of its interest-rate hedges during 2022, as rates rose. |
| `htm_reliance` | Losses hidden by held-to-maturity accounting. | `htm_share_of_securities`: < 10% -> 1, 10% -> 2, 25% -> 3, 40% -> 4, 60% -> 5. | 3; 5 if any verdict flips along `htm_treatment` (`comparison.flips`, or detected from grid pairs). | No control data: adequate. | HTM accounting kept SVB's roughly USD 15bn unrealised losses out of capital until forced sales realised them. If the verdict depends on the accounting, the bank is solvent on paper only. |
| `wholesale_dependence` | Funding that can vanish in stress. | Wholesale / (deposits + wholesale), from the dataset: < 5% -> 1, 5% -> 2, 10% -> 3, 20% -> 4, 30% -> 5. | 3; +1 if any wholesale line matures within 30 days. | Liquidity break-even outflow (`q2.reverse_stress`, target liquidity): strong >= 30%, adequate >= 15%, weak below. | Northern Rock (2007) funded most of its lending in wholesale and securitisation markets and failed when they closed. Continental Illinois (1984) was run by wholesale depositors. |
| `risk_governance` | Quality of risk oversight. | Score from recognised `governance` fields (below); likelihood = 1 + score, capped at 5. Unassessed if none is present. | 4 | Weak if the CRO seat has been vacant for 3 months or more, or the board lacks risk expertise; strong if at least 3 indicators are reported and none is adverse; adequate otherwise. | SVB had no chief risk officer for about eight months in 2022, the year its rate risk grew most (Federal Reserve review, April 2023). |
| `credit_concentration` | Dependence on the largest loan pool. | Largest pool EAD share: < 25% -> 1, 25% -> 2, 35% -> 3, 50% -> 4, 70% -> 5. | 3; +1 if that pool's PD >= 3%. | Weak if `loan_reconciliation_gap` >= 5% (the credit view does not match the books); adequate otherwise. | Continental Illinois's energy-loan concentration (Penn Square) and US commercial real estate in the early 1990s show how one sector can sink a bank. |

**Governance fields recognised** (`dataset.governance`), with score contributions:
`cro_vacancy_months` (> 0: +1, >= 3: +2, >= 6: +3); `board_risk_expertise` false: +1;
`risk_committee_meetings_per_year` < 4: +1; `limit_breaches_last_year` > 0: +1, >= 5: +2;
`independent_model_validation` false: +1; `open_supervisory_findings` > 0: +1;
`hedges_reduced_last_year` true: +1.

## Q3: transition risk ("how exposed, and how good is the data?")

| Factor | Measures | Rule (likelihood) | Impact | Control | Why it matters |
|---|---|---|---|---|---|
| `emissions_coverage` | MV share with reported scope 1 and 2. | `coverage_scope12` (lower is worse): >= 90% -> 1, < 90% -> 2, < 75% -> 3, < 60% -> 4, < 40% -> 5. | 3 | `q3.data_quality` label: good -> strong, fair -> adequate, poor -> weak. | Exposure measured on proxies can look aligned when it is not. Coverage is the first disclosure item under TCFD and ISSB S2. |
| `estimated_emissions` | Imputed share of financed emissions. | Largest `estimated_share` across the grid: < 10% -> 1, 10% -> 2, 25% -> 3, 40% -> 4, 60% -> 5. | 3 | MV-weighted PCAF-style `mean_data_quality`: strong <= 2, adequate <= 3.5, weak above. | Sector-average estimates hide differences between issuers. PCAF requires a data-quality score next to financed emissions for this reason. |
| `scope3_coverage` | MV share with value-chain emissions. | `coverage_scope3` (lower is worse): >= 75% -> 1, < 75% -> 2, < 50% -> 3, < 30% -> 4, < 10% -> 5. Notes whether any scenario included scope 3. | 3; 4 if energy, utilities and materials are >= 20% of long MV. | No control data: adequate. | For oil and gas, scope 3 (use of sold products) is most of the footprint, so ignoring it understates transition exposure. |
| `stale_data` | MV share with out-of-date emissions. | `stale_share`: 0 -> 1, > 0 -> 2, 10% -> 3, 25% -> 4, 50% -> 5. Cites stale findings. | 2 | No control data: adequate. | Old figures miss both decarbonisation progress and growth, so the measure lags reality. |
| `controversies` | MV share with controversy flags. | `controversy_share`: 0 -> 1, > 0 -> 2, 5% -> 3, 15% -> 4, 30% -> 5. Names the flagged issuers. | 3 | No engagement data: adequate. | Volkswagen was highly rated on ESG before the 2015 emissions scandal: controversies show where reported data cannot be trusted. |
| `exclusion_breaches` | Long holdings that breach the stated exclusion policy. | Any long holding with `exclusion_flags` -> 5, none -> 1 (shorts are not breaches). | 3 with no breach; with breaches, from the breached share of long MV: < 2% -> 3, 2% -> 4, 10% -> 5. | A breach shows the screen is not enforced: weak; otherwise adequate. | Greenwashing enforcement: the SEC fined DWS USD 19m (2023), Goldman Sachs Asset Management USD 4m (2022) and BNY Mellon Investment Adviser USD 1.5m (2022) for ESG claims and policies not matched by practice. |
| `high_emitting_concentration` | Long MV share in energy, utilities and materials. | Share (sector name contains "energy", "utilit" or "material"): < 10% -> 1, 10% -> 2, 20% -> 3, 30% -> 4, 45% -> 5. Cites `waci`. | 4 | No transition-plan data: adequate. | Carbon-price and stranded-asset risk falls mainly on these sectors (NGFS scenarios; the "carbon bubble" argument). |
| `scenario_dispersion` | How much the answer depends on assumptions. | Max/min `loss_pct` across the grid (`comparison.metric_ranges`): < 1.5 -> 1, 1.5 -> 2, 2.5 -> 3, 4 -> 4, 8 -> 5 (5 if the minimum is <= 0 and the maximum is positive). Quotes both ends and their parameters. | From the worst `loss_pct`: < 2% -> 1, 2% -> 2, 5% -> 3, 10% -> 4, 20% -> 5. | Scenario analysis is itself the control: adequate. | A single scenario number can mislead: climate scenario losses are deeply uncertain, and the range is the honest result. |

---

## Design notes and limitations

- **Judgment.** Thresholds are conventions chosen to be defensible (several track supervisory levels, such
  as the Basel traffic light and the IRRBB 15% outlier test), not estimates from loss data. Calibrate them to the
  institution's risk appetite before relying on them.
- **Representative values.** Where the grid has many values, rules quote an actual metric value (lower
  median, minimum or maximum) rather than an average, so it can be traced and verified.
- **Fallbacks.** If the comparator omits `method_spread`, `label_counts` or HTM flips, the rule computes the
  same quantity from the grid results with the definitions in CONTRACT.md section 4.3.
- **Control strength** is inferred only from evidence in the data (buffers, hedges, governance flags,
  reconciliation, backtests). Without such evidence it defaults to adequate, which may flatter residual
  ratings.
- **Governance** uses a recognised list of free-form keys; other keys are ignored. See
  `CONTRACT_REQUESTS.md`.
- **Dataset-derived numbers** (weights, funding shares) are described in words, not digits, because the
  contract's verifier matches numbers only against metric values.
- **Factor interactions** (e.g. uninsured deposits combined with HTM losses, as at SVB) are reflected only
  through impact adjustments and the worst-residual overall rating, not a joint model.
