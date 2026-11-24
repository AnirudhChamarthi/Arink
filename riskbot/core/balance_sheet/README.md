# Q2 balance-sheet models (`riskbot.core.balance_sheet`)

Model documentation for the three Q2 models: **could a bank-like balance sheet survive a rate shock combined
with a deposit run?**

| Model id | Module | Purpose |
|---|---|---|
| `q2.resilience` | `resilience.py` (+ `engine.py`) | Instantaneous rate shock + 30-day run: EVE, NII, credit loss, fire sales, capital, LCR, verdict |
| `q2.reverse_stress` | `reverse_stress.py` | Smallest uniform deposit outflow / rate shock that breaches capital or liquidity |
| `q2.data_quality` | `data_quality.py` | Reconciliation and structural indicators + findings for the Q2 rubric |

Supporting modules: `instruments.py` (bond, Vasicek and fire-sale maths), `validation.py` (input checks),
`sample.py` (synthetic bank). Package exports: `models()` and `sample_dataset(seed=0)`.

> **Status of the numbers.** This is an educational stress-testing model on synthetic data. Every threshold,
> run-off rate, haircut, the deposit-duration rule and the fire-sale impact are **illustrative**. They are not
> the rules of any jurisdiction (not Basel III LCR, not US or EU IRRBB rules, not any supervisory stress test)
> and must not be used for regulatory reporting.

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| $\Delta y$ | parallel rate shock, `rate_shock_bp / 10 000` |
| $MV_j, B_j$ | market and book value of asset $j$ |
| $D_j, C_j$ | modified duration and convexity of asset $j$ |
| $D_s, \beta_s, \iota_s, r_s$ | balance, rate beta, insured share and 30-day run-off rate of deposit segment $s$ |
| $W_w, m_w$ | amount and maturity (days) of wholesale line $w$ |
| $N_h$ | swap notional |
| $\lambda$ | fire-sale impact (`fire_sale_impact`) |
| $q$ | Vasicek factor quantile: 0.90 (`base`), 0.99 (`adverse`) |

All amounts are in the dataset currency. Losses are positive; `delta_*` metrics are signed.

## 2. `q2.resilience`

### 2.1 Duration and convexity

If an asset supplies `modified_duration` (and optionally `convexity`) they are used. Otherwise the asset is
treated as an annual-coupon bullet bond **priced at par**, i.e. with yield $y$ equal to its coupon $c$
(a zero- or negative-coupon instrument is discounted at the policy rate). The maturity used is the time to the
next repricing capped at final maturity, $T = \min(\text{repricing}, \text{maturity})$, so floating-rate loans
have short durations; cash has zero duration. With $n = \lceil T \rceil$ cash flows at $t_i = T-(n-i)$
(coupon $c$, plus face 1 at $T$):

$$
P(y)=\sum_i CF_i(1+y)^{-t_i},\qquad
D^{mac}=\frac{1}{P}\sum_i t_i\,CF_i(1+y)^{-t_i},\qquad
D=\frac{D^{mac}}{1+y},\qquad
C=\frac{1}{P}\sum_i t_i(t_i+1)\,CF_i(1+y)^{-t_i-2}.
$$

For integer $T$ at par, $D^{mac} = \frac{1+y}{y}\left(1-(1+y)^{-T}\right)$; for a zero-coupon bond
$D = T/(1+y)$, $C = T(T+1)/(1+y)^2$. A given duration without convexity receives the convexity of the
zero-coupon bond with that duration, $C = D^2 + D/(1+y)$.

### 2.2 Economic value of equity

$$
\Delta V_j = MV_j\left(-D_j\Delta y + \tfrac12 C_j \Delta y^2\right),\qquad \Delta A = \sum_j \Delta V_j
$$

Liabilities (value change, negative when rates rise):

$$
\Delta L = -\sum_s D_s \cdot 2(1-\beta_s)\,\Delta y \;-\; \sum_w W_w \frac{m_w}{365}\Delta y
$$

i.e. non-maturity deposits have an **assumed** effective duration of $2(1-\beta_s)$ years and wholesale
funding a duration equal to its maturity. Pay-fixed swaps gain
$\Delta S_h = +N_h D^{swap}_h \Delta y$ (receive-fixed: $-N_h D^{swap}_h\Delta y$) where $D^{swap}_h$ is the
modified duration of a par bond at the swap's fixed rate and maturity.

$$
\Delta EVE = \Delta A - \Delta L + \Delta S, \qquad \texttt{delta\_eve\_pct\_cet1} = \Delta EVE / CET1.
$$

### 2.3 Net interest income (12 months)

Static balance sheet; items repricing at $\tau<1$ year earn the shock for the rest of the year:

$$
\Delta NII = \sum_{j:\tau_j<1} B_j\Delta y(1-\tau_j) \;-\; \Big[\sum_s D_s\beta_s\Delta y + \sum_{w:m_w<365} W_w\Delta y\left(1-\tfrac{m_w}{365}\right)\Big] \;\pm\; \sum_h N_h\Delta y
$$

(cash reprices immediately; deposits reprice at once by $\beta_s\Delta y$; pay-fixed swaps receive floating).
NII is reported but **does not change capital** (assumption).

### 2.4 Credit loss

Vasicek (2002) one-factor stressed PD at factor quantile $q$:

$$
PD^{s}_p = \Phi\!\left(\frac{\Phi^{-1}(PD_p)+\sqrt{\rho_p}\,\Phi^{-1}(q)}{\sqrt{1-\rho_p}}\right),\qquad
CL = \sum_p EAD_p\,LGD_p\,PD^s_p .
$$

This is the $q$-quantile of the default rate of an infinitely granular homogeneous pool (the formula behind
the Basel IRB risk weights, here used only as a stress generator). LGD is not stressed; losses are recognised
immediately in full.

### 2.5 Deposit run and wholesale funding

$$
O_D = \sum_s D_s r_s, \qquad r_s = 0 \;(\texttt{none}),\ \texttt{runoff\_slow},\ \texttt{runoff\_fast}
$$

In slow and fast runs wholesale lines with $m_w \le 30$ days are not rolled over: $O_W = \sum_{m_w\le30}W_w$
(0 with `none`). Total need $N = O_D + O_W$. Reported `deposit_outflow` $= O_D$.

### 2.6 Liquidation waterfall and fire sales

1. Cash: $U_{cash} = \min(N, \text{cash})$.
2. HQLA securities, sold pro rata at their post-shock market value $MV^{post}_j = MV_j + \Delta V_j$
   (no discount).
3. AFS, then HTM securities at the fire-sale price $p(s) = e^{-\lambda s}$, where $s$ is the share of the
   post-shock AFS+HTM market value $S$ that is sold. The remaining need $N'$ satisfies

$$
\text{proceeds}(s) = s\,S\,e^{-\lambda s} = N'.
$$

Solved by fixed-point iteration $s_{k+1} = \frac{N'}{S}e^{\lambda s_k}$ from $s_0 = 0$. The map is increasing
and convex with $g'(s^*) = \lambda s^*$, so for $\lambda\le1$ the iterates increase monotonically to the
smallest root; convergence is checked ($|s_{k+1}-s_k| \le 10^{-12}$) and bisection finishes the job if 200
iterations are not enough (only as $\lambda s^* \to 1$). Proceeds increase on $[0, 1/\lambda] \supseteq [0,1]$,
so the maximum is $S e^{-\lambda}$: if $N' > Se^{-\lambda}$ everything is sold and the
**liquidity shortfall** $N' - Se^{-\lambda}$ is recorded (trace step `liquidity_shortfall`, warning).
The market value sold, $sS$, is taken from AFS first, then HTM; within a class pro rata.

**Realised loss** = carrying value of what was sold (pro rata) − proceeds, where the carrying value is the
pre-shock market value for HQLA/AFS (fair-value securities) and book value for HTM. `fire_sale_loss` is the
realised loss of all forced sales (HQLA + AFS + HTM).

### 2.7 Capital

$$
CET1' = CET1 - CL - RL - \sum_{j\in HQLA,AFS}(1-f_j)\,(MV_j - MV^{post}_j) - \mathbb{1}_{MTM}\sum_{j\in HTM}(1-f_j)(B_j - MV^{post}_j)
$$

with $f_j$ the share of security $j$ sold. Capital ratio $= CET1'/RWA$, RWA unchanged (assumption).
`unrealised_securities_loss` $= -\sum_{j\in\text{securities}}\Delta V_j$ is the shock loss on all securities
before any sale (positive = loss).

Accounting interpretation (documented deviation from a literal "book − proceeds" reading): HQLA and AFS
securities are carried at fair value with their pre-shock marks already in reported CET1, so only shock and
fire-sale losses hit capital; HTM securities are carried at amortised (book) value, so selling them
crystallises their embedded pre-shock loss, and marking them to market charges book − post-shock value.
This avoids double-counting AFS marks and makes the SVB mechanism (HTM losses crystallised by a run)
explicit. Consequences: with no shock and no run $CET1' = CET1 - CL$; without fire sales every HQLA/AFS
shock loss lands in capital whether sold or not (both tested).

### 2.8 LCR (illustrative)

$$
LCR = \frac{\sum_{j} MV_j(1-h_j)}{\sum_s D_s\,(0.05\,\iota_s + 0.25\,(1-\iota_s)) + \sum_{m_w\le30}W_w},\qquad
h = 0\% \text{ (level 1)},\ 15\%\ (2a),\ 50\%\ (2b).
$$

Cash is level 1; HQLA securities without a level are treated as level 1 (data-quality warning); AFS/HTM
securities count only if they carry a level. No level-2 caps, no inflows. `lcr_before` uses the unstressed
sheet. `lcr_after` uses the HQLA left after the waterfall at post-shock values, over the outflows on the
remaining deposits $D_s(1-r_s)$, plus short wholesale lines not repaid during the run (only with `none`). LCR
is capped at 100 (finite when outflows vanish) and set to 0 when a liquidity shortfall remains.

### 2.9 Verdict

`verdict = pass` iff $CET1'/RWA \ge$ `capital_threshold` and $LCR' \ge$ `lcr_threshold` (a shortfall always
breaches liquidity). `binding_constraint` ∈ {none, capital, liquidity, both}.

### 2.10 Trace

One step per intermediate quantity (`rate_shock`, `asset_durations` table, `delta_assets` per asset,
`delta_liabilities` per segment/line, `delta_swaps`, `delta_eve`, NII components, `credit_loss` per pool,
`unrealised_securities_loss` per security, `deposit_outflow` per segment, `wholesale_outflow`,
`liquidity_need`, `cash_used`, `hqla_securities_sold`, `fire_sale_pool`, `fire_sale_iterations` (table of
$k, s_k$, proceeds), `fire_sale_price`, `fire_sale_proceeds`, `liquidity_shortfall`, `fire_sale_loss`,
capital charges, `cet1_after`, capital ratios, HQLA/outflow/LCR before and after, `verdict`). Every metric
links to the step of the same name.

## 3. `q2.reverse_stress`

Uses `engine.evaluate` directly (same code as `q2.resilience`), with the resilience defaults: capital threshold
7%, LCR threshold 1.0, base credit severity, $\lambda = 0.05$.

* `breakeven_deposit_outflow`: every segment's run-off replaced by a uniform $x\in[0,1]$ (short wholesale not
  rolled over), shock fixed at `rate_shock_bp`; $x^* = \min\{x : \text{breach}(x)\}$.
* `breakeven_rate_shock_bp`: shock in $[0, 1000]$ bp with the slow-run rates.

Breach: $CET1'/RWA <$ threshold (`target=capital`) or $LCR' <$ threshold or shortfall (`target=liquidity`).

Algorithm: an 11-point grid checks that the breach indicator is non-decreasing and the constrained quantity
non-increasing (warning otherwise); if the lower end breaches the breakeven is the lower end; if the upper end
does not, the metric is omitted and the label is `no`; otherwise bisection on the first breaching grid bracket
until the bracket is $\le$ `tolerance` (outflow) or `tolerance`×1000 bp (rate). The reported value is the
upper end of the final bracket: it breaches, and $x^* - \text{tol}$ does not (tested). Trace: grid table,
bisection iterations table, verification at $x^*$ and $x^*-\text{tol}$.

## 4. `q2.data_quality`

| Metric | Definition |
|---|---|
| `loan_reconciliation_gap` | $\lvert\sum EAD - B_{loans}\rvert / B_{loans}$ |
| `uninsured_deposit_share` | $\sum_s D_s(1-\iota_s)/\sum_s D_s$ |
| `largest_segment_share` | $\max_s D_s / \sum_s D_s$ |
| `hqla_share` | MV of HQLA-eligible assets (pre-haircut) / total asset MV |
| `duration_gap_years` | $D_A - \frac{L}{A}D_L$ (MV-weighted asset duration, liabilities = deposits + wholesale) |
| `hedge_ratio` | pay-fixed swap notional / MV of fixed-rate securities (repricing ≥ maturity > 0) |
| `htm_share_of_securities` | HTM MV / securities MV |

Findings (illustrative thresholds): reconciliation gap > 2% warning, > 10% error; uninsured share > 50%;
single segment > 40%; no hedges while fixed-rate securities > 20% of assets; thin hedging (< 25% coverage);
duration gap > 3 years; HQLA security without a level; repricing after maturity; fast run-off below slow
(error); zero market value with book value (error); securities below 85% of book (info); assets minus modelled
liabilities below CET1; governance evidence (CRO vacancy, hedges reduced, two-year deposit growth > 50%).
Quality: `poor` if gap > 10% or any error; `fair` if any warning; else `good`.

## 5. Sample dataset (`sample_dataset(seed=0)`)

Synthetic regional bank, as of 2026-10-30, policy rate 4%: ~10.1bn assets (book); cash 1.05bn; 2.6bn
long-dated low-coupon securities (HQLA level 1 Treasuries and level 2a agencies, AFS MBS, HTM Treasuries /
MBS / munis, HTM ≈ half), market values from full revaluation at a 4.5% market yield (embedded losses);
6.15bn loans (fixed and floating) in four pools reconciling within 0.4%; deposits 7.3bn (~72% of the balance
sheet) in four segments, the largest a 94%-uninsured venture/tech segment (41%); a 21-day FHLB advance and a
270-day repo; one 150m pay-fixed swap; CET1 0.85bn, RWA 7.2bn (11.8%); governance red flags. `seed` jitters
balances by ≤0.5%.

Designed behaviour (tested): +100 bp / slow / base / at cost **passes** (9.6%, LCR 1.47); +300 bp / fast /
adverse / mark to market **fails** both constraints (liquidity shortfall). Across the default 32-variation
grid the verdict flips with `run_speed`, `htm_treatment` and `loss_severity`.

## 6. Assumptions (complete list)

1. Instantaneous parallel shift; no curve twists, basis, spread or optionality (prepayment, deposit migration).
2. Par-bond yield = coupon for derived durations (ignores the yield implied by market value); annual coupons.
3. Second-order Taylor revaluation for all assets.
4. Non-maturity deposit duration $2(1-\beta)$ years; wholesale duration = maturity; no liability convexity.
5. Swap value change from par-bond duration of the fixed leg; floating leg resets immediately.
6. NII on a static balance sheet; no capital effect of NII.
7. Vasicek stressed PD, unstressed LGD, one-year loss recognised at once; EAD from loan pools.
8. Run-off over 30 days applied instantaneously; short wholesale not rolled over in slow/fast runs.
9. Liquidation order cash → HQLA → AFS → HTM; HQLA sold at fair value; AFS/HTM at a common fire-sale price.
10. Fair-value accounting for HQLA/AFS (marks already in CET1), amortised cost for HTM (see 2.7).
11. Loans, other assets and liabilities stay at book value for capital; ΔEVE reported, not deducted.
12. RWA unchanged; no management actions, central-bank facilities, taxes or dividends.
13. LCR simplified (no level-2 caps, no inflows, two deposit categories), capped at 100.
14. All thresholds, run-off rates, haircuts and the fire-sale impact are illustrative.

## 7. Parameters

As declared in `riskbot/contract/catalog.py` (`Q2_RESILIENCE`, `Q2_REVERSE_STRESS`, `Q2_DATA_QUALITY`);
models call `conformance.resolve_params` and return the effective parameters.

## 8. Validation and tests (`tests/`)

| Formula | Independent oracle |
|---|---|
| Zero-coupon duration/convexity | closed form $T/(1+y)$, $T(T+1)/(1+y)^2$ |
| Par-bond duration | closed form $\frac{1+y}{y}(1-(1+y)^{-T})$ |
| Derived duration/convexity | central finite differences of full cash-flow repricing |
| Taylor revaluation | full revaluation at ±100 bp (error < 6e-4, better than duration alone) |
| Vasicek PD | hand-computed value (stdlib `NormalDist`), obligor-level Monte Carlo of the one-factor model |
| Credit loss | linearity in EAD |
| Fire sale | λ = 0 sells exactly the need; fixed point satisfies proceeds = need and is the smallest root; shortfall closed form; near-tangency bisection fallback |
| Whole engine | small bank recomputed by hand (EVE, NII, credit, outflow, HQLA sale, CET1, LCR before/after, MTM) |
| Properties | capital monotone decreasing in the shock (−200…600 bp), MTM ≤ at cost for non-negative shocks, faster runs never raise LCR |
| Reverse stress | breach at $x^*$ and none at $x^*-$tol; recovery of a known threshold; non-monotone case flagged; consistency with `q2.resilience` |
| Contract | every default-plan variation and extra conforms; determinism; wrong dataset kind / bad data → `ValidationFailed` |

## 9. Limitations

* **Large shocks:** the quadratic approximation has a vertex at $\Delta y = D/C$; beyond it the approximated
  loss shrinks (e.g. ≈ 700 bp for a 15-year bond). A warning is emitted per asset; the reverse-stress rate
  search may then be non-monotone (warned).
* Duration from the coupon rather than the market yield overstates duration for deep-discount bonds.
* No behavioural modelling of deposits (betas and run-off are inputs), no prepayment/extension risk in MBS.
* One-period, instantaneous: no dynamic balance sheet, no funding from central-bank facilities or repo of
  HTM securities, no contagion between the run and the rate shock other than through forced sales.
* Fire-sale price impact is a single-parameter exponential, common to all AFS/HTM securities.
* Credit losses ignore concentration (granularity) adjustments and correlation with the rate shock.
* LCR and thresholds are illustrative; the model is not a regulatory calculation.

## 10. References

* Vasicek, O. (2002). *The distribution of loan portfolio value.* Risk, 15(12).
* Basel Committee on Banking Supervision (2005). *An explanatory note on the Basel II IRB risk weight functions.*
* Basel Committee on Banking Supervision (2013). *Basel III: The Liquidity Coverage Ratio and liquidity risk
  monitoring tools* (structure only; parameters here are illustrative).
* Basel Committee on Banking Supervision (2016). *Interest rate risk in the banking book* (EVE/NII concepts).
* Fabozzi, F. J. *Bond Markets, Analysis and Strategies* (duration and convexity).
* Saunders, A. & Cornett, M. M. *Financial Institutions Management* (duration gap, liquidity risk).
* Greenwood, R., Landier, A. & Thesmar, D. (2015). *Vulnerable banks.* Journal of Financial Economics
  (fire-sale price impact).
* Board of Governors of the Federal Reserve System (2023). *Review of the Federal Reserve's supervision and
  regulation of Silicon Valley Bank* (motivation for the sample design).
