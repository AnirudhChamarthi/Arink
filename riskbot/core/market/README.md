# `riskbot.core.market`: Q1 market-risk models (model documentation)

**Question Q1:** *How much could this portfolio lose in a bad week, and how far should we trust that number?*

| Model id | Class | Purpose |
|---|---|---|
| `q1.var` | `var_model.VarModel` | Portfolio VaR and expected shortfall (ES) by six methods, with an optional bootstrap interval and rolling backtest |
| `q1.data_quality` | `data_quality.DataQualityModel` | Missing values, stale series, outliers, history length |

Package entry points: `models()` and `sample_dataset(seed=0)`. The models are pure. They do no I/O and use
no clock. The only randomness is `numpy.random.default_rng(seed)`, so the same (dataset, params, seed) always
gives the same output, trace ids included. Every metric links to a trace step with the same value.

Module layout: `estimators.py` (pure numerical formulas, one function per formula), `_data.py` (weights and
cleaning), `var_model.py`, `data_quality.py`, `sample.py`.

---

## 1. Common set-up for `q1.var`

### 1.1 Weights and portfolio returns

$$
MV_i = q_i p_i \;(\text{cash: } MV_i = q_i),\qquad G=\sum_i |MV_i|,\qquad w_i = \frac{MV_i}{G}
$$

Weights are signed, so shorts have negative weights, and $\sum_i |w_i| = 1$. Cash is in $G$ and has a zero
return. With $R\in\mathbb R^{n\times k}$ the simple daily returns of the non-cash holdings, the historical
portfolio return series is $r_p = Rw$. All VaR/ES figures are **fractions of gross exposure**. Currency
amounts are $VaR\cdot G$ and $ES\cdot G$.

### 1.2 Data handling

* **Missing values.** Any date with a missing return for a held ticker is dropped from the whole history
  (listwise deletion). This gives one `DataQualityFinding` (`missing_returns`) with the number of dropped dates.
* **Window.** The estimate uses the most recent `window_days` clean rows. If there are fewer, all rows are
  used, with a warning and a `short_window` finding.
* **Minimum history.** At least 30 clean observations, else `ValidationFailed`. A dataset of the wrong kind
  also raises `ValidationFailed`.

### 1.3 Losses, confidence and horizon

Loss is $L=-r_p$. VaR at confidence $c$ is the $c$-quantile of $L$, and $ES_c = E[L\mid L\ge VaR_c]$. Methods
1-5 compute a 1-day figure and scale it with $VaR_h = \sqrt h\,VaR_1$ and $ES_h=\sqrt h\,ES_1$. This assumes
i.i.d. returns. Monte Carlo simulates the $h$-day distribution directly.

---

## 2. Methods

### 2.1 `normal`: Gaussian, zero mean

$$
\sigma_p=\sqrt{w^\top\Sigma w},\qquad VaR_1 = z_c\,\sigma_p,\qquad ES_1=\sigma_p\,\frac{\varphi(z_c)}{1-c},\qquad z_c=\Phi^{-1}(c)
$$

$\Sigma$ is the unbiased sample covariance $S=\frac{1}{n-1}\sum_t(R_t-\bar R)(R_t-\bar R)^\top$, or the
Ledoit-Wolf estimate (§3), depending on `covariance`.
*Assumptions:* i.i.d. Gaussian returns with zero mean.
*Limitations:* thin tails, so it understates tail risk for equity returns; no volatility dynamics.

### 2.2 `student_t`: Student-t scaled to unit variance

$$
VaR_1=\sigma_p\,t_\nu^{-1}(c)\sqrt{\tfrac{\nu-2}{\nu}},\qquad
ES_1=\sigma_p\sqrt{\tfrac{\nu-2}{\nu}}\;\frac{f_\nu(t_c)}{1-c}\;\frac{\nu+t_c^2}{\nu-1}
$$

$\nu$ = `t_dof` ($>2$), $t_c=t_\nu^{-1}(c)$. Because of the factor $\sqrt{(\nu-2)/\nu}$, $\sigma_p$ is the
standard deviation of the distribution.
*Assumptions:* i.i.d. scaled-t returns with $\nu$ fixed by the user (not estimated).
*Limitations:* the tail weight is assumed, not estimated; there is one $\nu$ for the whole portfolio.

### 2.3 `historical`: historical simulation

$VaR_1 = Q_c(L)$, computed with `numpy.quantile` (linear interpolation, numpy's default "type 7");
$ES_1 = \text{mean}\{L_t : L_t \ge VaR_1\}$.
*Assumptions:* the window is representative of tomorrow.
*Limitations:* it is slow to react to volatility changes, and with 250 days at 99% the tail rests on 2-3
observations. The trace lists the tail losses.

### 2.4 `fhs`: filtered historical simulation (GARCH(1,1))

With $x_t=100\,r_{p,t}$ (percent units), fit a zero-mean Gaussian GARCH(1,1) by QMLE with `arch`:

$$
\sigma_t^2=\omega+\alpha x_{t-1}^2+\beta\sigma_{t-1}^2,\quad z_t=x_t/\sigma_t,\quad
\sigma_{T+1}^2=\omega+\alpha x_T^2+\beta\sigma_T^2
$$

The simulated losses are $\tilde L_t = -\sigma_{T+1} z_t/100$, with $VaR_1=Q_c(\tilde L)$ and
$ES_1=\text{mean}\{\tilde L\ge VaR_1\}$. The initial variance is `arch`'s backcast: the 0.94-weighted mean of
the first 75 values of $x^2$. Our own filter (`garch_filter`) reproduces `arch`'s conditional volatility and
forecast to 1e-10.
*Fallback:* if the optimiser fails, or the parameters are non-finite or explosive ($\alpha+\beta>1$), an
EWMA filter $\sigma_t^2=\lambda\sigma_{t-1}^2+(1-\lambda)x_{t-1}^2$ ($\lambda=0.94$,
$\sigma_0^2=\overline{x^2}$) is used and a warning is added. `arch` constrains $\alpha+\beta\le 1$, so a fit on
that boundary (integrated GARCH) is accepted with a warning: the one-step forecast is still finite.
*Assumptions:* i.i.d. standardised residuals.
*Limitations:* $\sqrt h$ scaling ignores mean reversion of volatility over the horizon. The GARCH is fitted to
the portfolio series, not to the assets, so it assumes the current weights were held through the window.

### 2.5 `evt`: peaks over threshold with a generalized Pareto tail

$u=Q_q(L)$ with $q$ = `evt_threshold_quantile`. The exceedances $y=L-u$ for $L>u$ (there are $N_u$ of them,
out of $n$) are fitted by MLE to a generalized Pareto distribution
$G_{\xi,\beta}(y)=1-(1+\xi y/\beta)^{-1/\xi}$ with `scipy.stats.genpareto.fit(y, floc=0)`. Then

$$
VaR_1=u+\frac{\beta}{\xi}\left[\left(\frac{n}{N_u}(1-c)\right)^{-\xi}-1\right]
\quad(\text{for } |\xi|<10^{-6}:\ u-\beta\ln(\tfrac{n}{N_u}(1-c))),\qquad
ES_1=\frac{VaR_1+\beta-\xi u}{1-\xi}
$$

At least 20 exceedances are required and $\xi<1$ (else ES is infinite); otherwise `ValidationFailed`. A warning
is added if $1-c \ge N_u/n$, because the formula is then used below the threshold.
*Assumptions:* exceedances are i.i.d. GPD (Pickands-Balkema-de Haan); no declustering.
*Limitations:* with a 250-day window there are only about 25 exceedances, so $\hat\xi$ is very uncertain (see
the bootstrap interval). The result is sensitive to $u$.

### 2.6 `montecarlo`: multivariate normal simulation

$\mu=\bar R$ (sample mean vector) and $\Sigma$ (sample or Ledoit-Wolf). Draw $Z\in\mathbb R^{N\times k}$ i.i.d.
$N(0,1)$ from `default_rng(seed)`, then

$$
X^{(s)} = h\mu+\sqrt h\,Z^{(s)}L^\top\sim N(h\mu,h\Sigma)\ (LL^\top=\Sigma),\qquad L^{(s)}=-w^\top X^{(s)}
$$

$VaR_h = Q_c(L^{(s)})$ and $ES_h$ is the tail mean. No $\sqrt h$ scaling. Unlike `normal`, this includes the
sample mean. It converges to $-h\,w^\top\mu+z_c\sqrt h\,\sigma_p$ (tested).
*Limitations:* Gaussian, so the same thin tails as `normal`; with 20,000 paths and $c=0.99$ the tail has about
200 points.

---

## 3. Ledoit-Wolf shrinkage to constant correlation

Ledoit & Wolf (2004), "Honey, I shrunk the sample covariance matrix". With demeaned returns $y_{ti}$,
$s_{ij}=\frac1T\sum_t y_{ti}y_{tj}$, and average correlation $\bar r$, the target is $f_{ii}=s_{ii}$,
$f_{ij}=\bar r\sqrt{s_{ii}s_{jj}}$, and

$$
\hat\pi=\sum_{ij}\tfrac1T\sum_t(y_{ti}y_{tj}-s_{ij})^2,\quad
\hat\rho=\sum_i\hat\pi_{ii}+\sum_{i\ne j}\tfrac{\bar r}{2}\Big(\sqrt{\tfrac{s_{jj}}{s_{ii}}}\hat\vartheta_{ii,ij}+\sqrt{\tfrac{s_{ii}}{s_{jj}}}\hat\vartheta_{jj,ij}\Big),\quad
\hat\gamma=\sum_{ij}(f_{ij}-s_{ij})^2
$$

with $\hat\vartheta_{ii,ij}=\frac1T\sum_t(y_{ti}^2-s_{ii})(y_{ti}y_{tj}-s_{ij})$. The intensity is
$\delta^*=\max(0,\min(1,(\hat\pi-\hat\rho)/(T\hat\gamma)))$ and the estimate is
$\hat\Sigma=\frac{T}{T-1}\big(\delta^*F+(1-\delta^*)S_{1/T}\big)$. The factor $T/(T-1)$ is our convention: it
makes $\delta^*=0$ give exactly the unbiased sample covariance used by the `sample` option. The trace reports
$\delta^*$ (`shrinkage_intensity`) and $\bar r$.
*Tests:* agrees to 1e-10 with a loop-by-loop transcription of the paper. On small simulated samples
($N=10, T=30$) the estimate is positive definite, has $\delta^*\in[0,1]$, and has a lower mean Frobenius error
than $S$. $\delta^*$ falls with $T$ when the target is misspecified.

---

## 4. Bootstrap interval (`bootstrap` = B > 0)

Moving-block bootstrap (Künsch 1989) of the rows of the estimation window. The block length is
$\ell=\text{round}(n^{1/3})$ (6 for 250 days, 9 for 750). Block starts are uniform on $[0,n-\ell]$; the blocks
are concatenated and cut to $n$ rows. Resampling whole rows keeps the cross-sectional dependence. For each
resample, VaR is re-computed with the same method, horizon and confidence. The interval is the 2.5% and 97.5%
percentiles (`var_ci_low`, `var_ci_high`). Choices made for speed:

* **montecarlo**: 5,000 paths per resample, with the same normal draws reused (common random numbers), so the
  interval shows estimation uncertainty in $(\mu,\Sigma)$, not simulation noise.
* **fhs**: *fast GARCH path*. The parameters stay at the full-window estimate (no re-fit). Each resample is
  re-filtered to get its standardised residuals, and $\sigma_{T+1}$ comes from the actual window. The interval
  therefore shows sampling error in the residual tail, **not** GARCH parameter uncertainty. A full re-fit on
  block-resampled series was tried and rejected: blocks break volatility clustering, the persistence is
  under-estimated, and the interval did not contain the point estimate.
* **evt**: the GPD is re-fitted with a fast profile-likelihood MLE (Grimshaw 1993), $\theta=\xi/\beta$,
  $\hat\xi(\theta)=\overline{\ln(1+\theta y)}$, maximising $\ell^*(\theta)=-n\ln(\hat\xi/\theta)-n\hat\xi-n$.
  This reaches a likelihood equal to or better than `scipy`'s fit (tested) and is about 15 times faster.

## 5. Backtest (`backtest` = true)

The same method is rolled over the whole clean history with a **250-day window, 1-day horizon and the same
confidence**, whatever `window_days` is. The forecast for day $t$ uses rows $t-250..t-1$ only. An exception is
$L_t > VaR_t$. This needs at least 251 clean rows; otherwise the backtest metrics are omitted, both labels are
`n/a` and a warning is added. Per-method choices:

* normal/student_t with sample covariance: $\sigma_t$ = rolling standard deviation of $r_p$, which equals
  $\sqrt{w^\top S_t w}$ exactly. With Ledoit-Wolf, $\hat\Sigma_t$ is re-estimated every day.
* montecarlo: the analytic quantile of $N(\mu_t,\Sigma_t)$, $-w^\top\mu_t+z_c\sigma_t$, which the simulation
  converges to. This avoids about 500 simulations.
* fhs: GARCH is re-fitted every 20 days with `arch`, warm-started. Each day the window is re-filtered with the
  fixed parameters. If a re-fit fails, EWMA is used for that block and a note is added.
* evt: the GPD is re-fitted daily with the fast MLE. If a window has fewer than 20 exceedances (e.g.
  `evt_threshold_quantile` > 0.92), the backtest is skipped with a warning.

Statistics, with $T$ days, $x$ exceptions and $p=1-c$:

* **Kupiec POF** (1995): $LR_{POF}=-2\ln\frac{(1-p)^{T-x}p^x}{(1-\hat p)^{T-x}\hat p^x}\sim\chi^2_1$,
  $\hat p=x/T$.
* **Christoffersen independence** (1998): with transition counts $n_{ij}$,
  $LR_{ind}=-2\ln\frac{(1-\pi)^{n_{00}+n_{10}}\pi^{n_{01}+n_{11}}}{(1-\pi_0)^{n_{00}}\pi_0^{n_{01}}(1-\pi_1)^{n_{10}}\pi_1^{n_{11}}}\sim\chi^2_1$.
* **Basel traffic light** on the last 250 forecasts: binomial CDF $F(x;250,p)$ < 0.95 green, < 0.9999
  yellow, else red. At 99% this gives the published 0-4 / 5-9 / 10+ zones (tested).
* **Verdict**: `rules.backtest_verdict` gives pass iff both p-values are at least 0.05.

---

## 6. `q1.data_quality`

The checks run over the return series of held non-cash tickers.

| Check | Rule | Finding |
|---|---|---|
| missing | count of `None` values; $\text{missing\_share}=\#\text{missing}/(n\cdot k)$ | `missing_returns` (warning), one per ticker |
| stale | longest run of returns exactly 0 is at least `stale_days` | `stale_series` (warning) |
| outliers | $\lvert r_t-m_t\rvert > 10\cdot 1.4826\,\text{MAD}_t$ with rolling median $m_t$ and $\text{MAD}_t$ over a centred 63-day window (≥ 20 values; contract 2.0.1) | `outlier_returns` (warning), one per ticker |
| short history | fewer than 250 non-missing values | `short_history` (error) |

Label: `poor` if missing_share > 5% or any series is short; `fair` if any finding is a warning; else `good`.
*Note:* the original global raw-MAD rule flagged about 200 genuine stress-period returns on the sample; the rolling
rule (contract 2.0.1) flags returns that are extreme relative to local volatility, i.e. likely data errors.

## 7. Sample dataset (`sample_dataset(seed=0)`)

A synthetic long/short equity book (`synthetic=True`):

* 13 equities in 9 sectors (3 of them short) plus one USD cash line; gross exposure about 10m.
* 780 business days ending 2026-10-30.
* Returns $r_{it}=\mu_i+\sigma_i m_t h_t(s_i\varepsilon^M_t+\sqrt{1-s_i^2}\varepsilon^i_t)$, where the
  $\varepsilon$ are standardised t(5) shocks and $h_t$ is a unit-variance GARCH(1,1) ($\alpha=0.08$,
  $\beta=0.90$) driven by the market shock. Conditional correlations are $s_is_j\in[0.25,0.6]$.
* Stress episode: $m_t=3$ for 60 days starting at day 150. This is inside the 750-day window and outside the
  250-day window, so the 750-day VaR is about 1.8-2.2 times the 250-day VaR.
* Defects: 6 missing HTLX returns and a run of 7 zero KILO returns.

## 8. Validation summary (test oracles)

| Formula | Oracle |
|---|---|
| Normal VaR/ES | published constants (2.326348, 2.665214) and numerical tail integral |
| Student-t VaR/ES | `scipy.stats.t` scaled to unit variance; ES by two numerical integrals; limit to normal as ν→∞ |
| Historical | equals `np.quantile`; hand-computed small sample |
| FHS | own filter equals `arch` to 1e-10; parameter recovery from simulated GARCH; rolling exception rate on simulated GARCH within [3.5%, 6.8%] for a 5% target |
| EVT | recovers ξ = 0.25 from simulated GPD data and from t(4) tails; POT quantile equals the GPD ppf for u = 0; ES equals a numerical integral; fast MLE equal to or better than scipy |
| Monte Carlo | converges to the analytic normal quantile (zero mean and sample-mean cases) |
| Ledoit-Wolf | loop transcription of the paper; δ in [0,1]; positive definite; lower Frobenius error |
| Kupiec / Christoffersen | binomial likelihood-ratio identity; brute-force Markov likelihood; Jorion's LR ≈ 12.96 for 10/250 |
| Basel zones | published 0-4 / 5-9 / 10+ table |
| Scaling, ES ≥ VaR | properties checked on every method and every default-plan variation |

## 9. Known limitations

* $\sqrt h$ scaling for methods 1-5 assumes i.i.d. returns. It ignores volatility clustering over the horizon
  and the positive drift.
* Weights are constant: there is no intra-horizon rebalancing, and the historical portfolio series is
  rebuilt with today's weights.
* Listwise deletion can remove many dates if one ticker is often missing. There is no imputation.
* The FHS bootstrap leaves out GARCH parameter uncertainty (§4). Block bootstrap intervals for
  tail quantiles from 250 points are themselves imprecise.
* The backtest window is fixed at 250 days, so the backtest figures are the same for `window_days` 250 and
  750 (`CONTRACT_REQUESTS.md` §2).
* Ledoit-Wolf shrinks to constant correlation, which is not suitable for books with strong sector blocks.

## References

* Barone-Adesi, G., Giannopoulos, K. and Vosper, L. (1999). VaR without correlations for portfolios of
  derivative securities. *Journal of Futures Markets* 19(5).
* Basel Committee on Banking Supervision (1996). *Supervisory framework for the use of "backtesting" in
  conjunction with the internal models approach to market risk capital requirements.*
* Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *J. Econometrics* 31.
* Christoffersen, P. (1998). Evaluating interval forecasts. *International Economic Review* 39(4).
* Grimshaw, S. (1993). Computing maximum likelihood estimates for the generalized Pareto distribution.
  *Technometrics* 35(2).
* Hull, J. and White, A. (1998). Incorporating volatility updating into the historical simulation method
  for VaR. *Journal of Risk* 1.
* Jorion, P. (2007). *Value at Risk*, 3rd ed., McGraw-Hill.
* Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement models. *J. Derivatives* 3.
* Künsch, H. (1989). The jackknife and the bootstrap for general stationary observations. *Ann. Statist.* 17.
* Ledoit, O. and Wolf, M. (2004). Honey, I shrunk the sample covariance matrix. *J. Portfolio Management* 30(4).
* McNeil, A., Frey, R. and Embrechts, P. (2015). *Quantitative Risk Management*, revised ed., Princeton.
* RiskMetrics Group (1996). *RiskMetrics Technical Document*, 4th ed.
