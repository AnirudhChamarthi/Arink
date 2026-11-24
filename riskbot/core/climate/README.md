# Q3 transition-risk model (`riskbot.core.climate`)

Model documentation for `q3.transition` and `q3.data_quality` (catalogue: `riskbot/contract/catalog.py`).

> **Illustrative only.** The carbon-price paths, price multipliers, sector pass-through rates, fallback
> sector intensities, pathway benchmark and decline rate are round numbers chosen for a teaching
> portfolio. The scenarios follow the *shape* of the NGFS families (orderly, disorderly, hot house
> world) but are **not NGFS data**. The sample portfolio is synthetic and its issuers are fictitious.
> Every number lives in `assumptions.py` (`TransitionAssumptions`) so that it can be replaced with
> sourced data.

## 1. Purpose and scope

Answers: *how exposed is this portfolio to the low-carbon transition, and how good is the data?*

* **Transition shock**: a direct carbon-cost repricing of each long equity holding under a carbon-price
  scenario, with uncertainty from estimated emissions.
* **Footprint**: weighted average carbon intensity (WACI), financed emissions and a pathway alignment ratio.
* **Data quality**: coverage, quality score, staleness and flags, weighted by market value.

Out of scope: demand destruction, stranded reserves, abatement capex, second-round (supply-chain) effects,
physical risk, credit spreads.

## 2. Package interface

```python
from riskbot.core.climate import models, sample_dataset
transition, data_quality = models()          # q3.transition, q3.data_quality
out = transition.run(sample_dataset(), {"scenario": "disorderly"}, seed=42)
```

Both models call `conformance.resolve_params`, raise `ValidationFailed` for a non-climate dataset (or no
long holdings, for `q3.transition`), build one trace with `TraceBuilder` (id from
`hashing.model_input_hash`) and link each metric to a trace step with the same value.

## 3. `q3.transition`: formulas

Notation: holding $i$, market value $MV_i$, enterprise value including cash $EVIC_i$, revenue $Rev_i$ (USD
million), sector $s(i)$, emissions $E_i$ (tCO2e/yr), scenario price path $P(t)$, multiplier $m$, horizon
$H$, discount rate $r = 5\%$.

### 3.1 Exposure set
Only long holdings are exposed: $\mathcal{L} = \{i : MV_i > 0\}$, $MV_{long} = \sum_{i \in \mathcal{L}} MV_i$.
Shorts (and zero positions) are listed in trace step `long_book` and a `short_excluded` finding.

### 3.2 Carbon-price paths (USD/tCO2e, illustrative), $t$ = years after the as-of year

$$
P_{orderly}(t) = \begin{cases} 60 + 10t & t \le 9 \\ 150 + 5(t-9) & t > 9 \end{cases}\qquad
P_{disorderly}(t) = \begin{cases} 35 & t \le 3 \\ 35 + \tfrac{215}{3}(t-3) & 3 < t \le 6 \\ 250 & t > 6 \end{cases}
\qquad P_{hot\_house}(t) = 35 + t
$$

Scaled price $p_t = m\,P(t)$ with $m \in \{0.5, 1, 2\}$ for `low`, `central`, `high`.
`carbon_price_end` $= p_H$.

### 3.3 Emissions
$E_i = S1_i + S2_i\ (+\,S3_i$ if `include_scope3` and $S3_i$ is available$)$. A holding is *reported* only
if both scope 1 and 2 are present (a lone scope is ignored and the holding is treated as missing).

Missing scope 1+2, by `missing_data`:

* `sector_average`: $\hat E_i = Rev_i \cdot \operatorname{median}\{I_j : j \text{ reports}, s(j) = s(i)\}$,
  $I_j = (S1_j+S2_j)/Rev_j$; peers include every reporting holding (also shorts: intensity is an issuer
  property). With no peer in the sector, the fallback table median is used.
* `conservative`: as above with the 75th percentile (linear interpolation; fallback table p75).
* `exclude`: the holding gets no emissions, no shock and no footprint; its MV is recorded in `long_book`.
  It stays in the loss denominator $MV_{long}$ (loss is a share of the whole long book).

Unknown sector strings (after lower-casing and mapping spaces/hyphens to `_`) map to `other` with an
`unknown_sector` finding.

### 3.4 Valuation shock (constant emissions)
$$
C_{i,t} = E_i\,p_t\,(1-\pi_{s(i)}),\qquad
PV_i = \sum_{t=1}^{H} \frac{C_{i,t}}{(1+r)^t} = E_i (1-\pi_{s(i)})\,A,\qquad
A = \sum_{t=1}^{H} \frac{p_t}{(1+r)^t}
$$
$$
c_i = \frac{PV_i}{EVIC_i},\qquad \text{shock}_i = -\min(c_i, 1),\qquad L_i = MV_i \min(c_i, 1)
$$
Costs are paid at the end of years $1..H$. The deterministic (point-estimate) loss
$\sum_i L_i / MV_{long}$ is trace step `central_loss`.

### 3.5 Uncertainty (Monte Carlo)
For draws $k = 1..N$ (`n_sims`) and $Z_{ki} \sim N(0,1)$ i.i.d. from `numpy.random.default_rng(seed)`:
$$
E_i^{(k)} = E_i\, e^{\sigma_i Z_{ki} - \sigma_i^2/2},\qquad
\ell^{(k)} = \frac{1}{MV_{long}} \sum_{i \in \mathcal{L}} MV_i \min\!\left(c_i\, e^{\sigma_i Z_{ki} - \sigma_i^2/2},\ 1\right)
$$
The factor has mean 1 (mean-preserving) and median $e^{-\sigma^2/2} < 1$, so `loss_pct` (the median of
$\ell^{(k)}$) is typically slightly below the central loss. `loss_p05`, `loss_p95` are empirical
quantiles (numpy linear interpolation); `loss_amount` $=$ `loss_pct` $\times MV_{long}$.

$\sigma$ by data quality: 1: 0.05, 2: 0.10, 3: 0.20, 4: 0.35, 5 or missing: 0.50; imputed: 0.60.

`exposure_level`: low if `loss_pct` < 2 %, moderate if < 8 %, else high (illustrative thresholds).

### 3.6 Footprint (PCAF attribution, TCFD WACI)
Covered set $\mathcal{C} \subseteq \mathcal{L}$: long holdings with reported or imputed $E_i$;
$w_i = MV_i / \sum_{j \in \mathcal{C}} MV_j$.
$$
WACI = \sum_{i \in \mathcal{C}} w_i \frac{E_i}{Rev_i},\qquad
FE = \sum_{i \in \mathcal{C}} \frac{MV_i}{EVIC_i} E_i,\qquad
\text{estimated\_share} = \frac{\sum_{i \in imputed} \frac{MV_i}{EVIC_i}E_i}{FE}
$$

### 3.7 Alignment
$$
I^{path} = \Big(\sum_s w_s B_s\Big)(1-d)^{(year_{as\_of} - 2020)},\quad d = 0.07,\qquad
\text{alignment\_ratio} = \frac{WACI}{I^{path}}
$$
with $w_s$ the covered-weight share of sector $s$ and $B_s$ the illustrative 2020 benchmark intensity.
A ratio above 1 means the book is more carbon-intensive than its own sector mix on the pathway; because
the benchmark is sector-weighted, the ratio measures selection *within* sectors plus the pathway decline,
not sector allocation.

## 4. Parameters (all illustrative)

| Sector | pass-through $\pi$ | fallback median (t/USDm) | fallback p75 | benchmark 2020 $B_s$ |
|---|---|---|---|---|
| energy | 0.3 | 550 | 900 | 600 |
| utilities | 0.5 | 1400 | 2600 | 1500 |
| materials | 0.3 | 700 | 1300 | 800 |
| industrials | 0.4 | 120 | 250 | 150 |
| transportation | 0.4 | 400 | 750 | 450 |
| consumer | 0.6 | 50 | 110 | 60 |
| technology | 0.8 | 12 | 30 | 15 |
| financials | 0.8 | 8 | 20 | 10 |
| health_care | 0.8 | 20 | 45 | 25 |
| real_estate | 0.5 | 70 | 150 | 80 |
| other | 0.5 | 100 | 250 | 120 |

Discount rate 5 %; price multipliers 0.5 / 1 / 2; pathway decline 7 %/yr from 2020.

Units: `market_value`, `evic` and `revenue` are read in currency units (USD assumed for carbon prices);
revenue is divided by $10^6$ for intensities (see `CONTRACT_REQUESTS.md` #1).

## 5. `q3.data_quality`

Over long holdings with $w_i = MV_i/MV_{long}$:
`coverage_scope12` $=\sum w_i 1[S1_i, S2_i]$; `coverage_scope3` $=\sum w_i 1[S3_i]$;
`mean_data_quality` $=\sum w_i q_i$ with $q_i = 5$ when `data_quality` is missing or scope 1/2 is
missing; `stale_share` $=\sum w_i 1[year_i < year_{as\_of} - \text{stale\_years}]$ (unknown year is not
stale); `controversy_share` $=\sum w_i 1[\text{flags}_i \ne \emptyset]$.
`quality`: poor if coverage_scope12 < 60 %; fair if < 85 % or stale_share > 20 %; else good.
Findings (one per issue per holding, long or short): `missing_scope12`, `missing_scope3`,
`stale_emissions`, `controversy`, `exclusion_breach`, `unknown_sector`.

## 6. Sample dataset

`sample_dataset(seed=0)`: 21 fictitious holdings (20 long, 1 short coal issuer) in 10 sectors, as of
2026-10-30; 6 of 21 miss scope 1-2 (MV coverage ~82 %), 17 miss scope 3, data quality 1-5 and missing,
one stale year (2021), three controversy flags, one exclusion flag. `seed` only jitters magnitudes (3 %
log-normal). On the default plan, `loss_pct` ranges from ~1 % (hot house, low) to ~20 % (disorderly,
high), so `exposure_level` spans low / moderate / high and flips with `missing_data` (orderly central:
high with imputation, moderate when missing holdings are excluded).

## 7. Validation (tests in `tests/`)

| Oracle | Test |
|---|---|
| Hand-computed 3-issuer book: central loss 0.30 (one holding capped), WACI 7.6, FE 16.25, alignment 7.6/429 | `test_hand_computed_three_issuer_example` |
| Flat-price annuity closed form $p(1-(1+r)^{-H})/r$ | `test_discounted_price_sum_closed_form_for_flat_price` |
| Price paths at knots | `test_price_paths_match_specification` |
| Zero price and full pass-through give zero loss | `test_zero_carbon_price_*`, `test_full_pass_through_*` |
| Monotone in `price_path`; cap at -100 %; quantiles ordered | property tests |
| $\sigma=0$ Monte Carlo = deterministic; mean-preservation by LLN | `test_sigma_zero_monte_carlo_equals_deterministic` |
| Median / p75 imputation by hand; conservative ≥ sector average; exclude ⇒ estimated_share 0 | imputation tests |
| Shorts excluded (metrics identical with/without the short) | `test_shorts_excluded` |
| Every default-plan variation and extra conforms; determinism; `ValidationFailed` | contract tests |
| Data-quality metrics by hand; label thresholds | `test_data_quality_and_sample.py` |

## 8. Limitations

* Direct cost channel only, with constant emissions and fixed pass-through: no abatement, no demand
  response, no margin dynamics; shocks for heavy emitters are therefore upper-bound-like and the cap at
  -100 % binds for some issuers under high paths.
* Full carbon price applies to all scope 1+2 (and optional scope 3) tonnes: no free allocation,
  no regional differentiation, no double-counting adjustment for scope 3.
* Equity-style shock: debt holdings would need a structural (Merton-type) mapping instead of $PV/EVIC$.
* Emission-error draws are independent across holdings; imputed holdings in the same sector share the same
  peer statistic, so true errors are correlated and the p05-p95 band is too narrow.
* The data-quality → $\sigma$ map, scenarios and all tables are illustrative, not calibrated.
* Peer statistics on very small peer groups (1-3 issuers) are noisy; one peer makes median = p75.
* No FX: carbon prices are applied in the dataset currency.

## 9. References

* PCAF (2022), *The Global GHG Accounting and Reporting Standard, Part A: Financed Emissions*, 2nd ed.
  — attribution factor $MV/EVIC$ for listed equity and corporate bonds; data-quality scores 1-5.
* TCFD (2021), *Implementing the Recommendations of the TCFD* (Annex) and *Guidance on Metrics, Targets,
  and Transition Plans* — weighted average carbon intensity.
* NGFS (2023), *NGFS Climate Scenarios for central banks and supervisors*, Phase IV — scenario families
  whose shapes are imitated here (no NGFS data used).
