# Benchmark protocol

**Version 1.0, fixed on 2026-11-23, before any results were produced.**
Changes after this date get a new version number and a changelog entry below; results are always
reported against the protocol version that produced them.

## 1. Purpose

Produce reproducible, numerical evidence about three things:

1. **Accuracy:** do the risk models measure tail risk correctly, and how do methods compare?
2. **Correctness:** do the tests actually catch errors in the math?
3. **Engineering:** how fast and how reproducible are the calculations?

The protocol is written so that a reviewer can re-run every benchmark from a clean clone and get
the same numbers (simulated benchmarks bit-for-bit; market benchmarks given the same data snapshot).

## 2. How this maps to real-world practice

The benchmarks mirror how banks and supervisors actually judge risk models. The analogies are
deliberately conservative: this project imitates the *form* of the evidence, at a much smaller
scale, and is not a regulatory submission.

| Benchmark here | Real-world counterpart | What the counterpart does |
| --- | --- | --- |
| VaR exception counts, Basel zones over 250-day blocks | Basel market-risk backtesting ("traffic light", 1996 framework) | Banks compare each day's 99% VaR with the next day's P&L over 250 days; the exception count puts the model in a green, yellow or red zone, and yellow/red raise the capital multiplier. |
| Backtesting at both 97.5% and 99% | The revised market-risk framework (FRTB) | Capital moved to 97.5% expected shortfall, while desk-level model approval still backtests VaR at 97.5% and 99%. |
| Kupiec and Christoffersen tests | Standard statistical backtests in validation practice | Unconditional coverage (right number of exceptions) and independence (exceptions not clustered). |
| Simulated data with a known true VaR | Known-answer testing and challenger models by independent validators | Validators test a model where the right answer is known before trusting it where it is not. |
| Crisis-window replays (2008, 2020, 2022) | Stressed VaR (Basel 2.5) and supervisory stress periods | Models are judged specifically on periods of significant stress, where calm-period models typically fail. |
| Comparison of methods on the same data | "Benchmarking" and "outcomes analysis" in model-risk guidance (US SR 11-7, Canada OSFI E-23) | Guidance expects models to be compared against alternative approaches and their outcomes analysed. |
| Quantile (tick) loss vs an oracle | Forecast-comparison practice in the academic VaR literature | A proper scoring rule for quantile forecasts, so methods can be ranked, not just passed or failed. |
| Mutation testing (planned, §6) | Effective challenge in model validation | Validation must be capable of finding problems; mutation testing measures whether the test suite would catch an injected error. |
| Calculation latency and batch time | End-of-day risk batch windows and intraday recalculation | Risk numbers must be produced within an operational window. |
| This document, fixed before running | Validation plans agreed before testing | Prevents choosing favourable tests after seeing results ("backtest overfitting"). |

## 3. Benchmark A: simulated truth

**Question:** when the true VaR is known exactly, how close does each method get, and do the
standard tests behave as theory says?

### Data-generating processes (DGPs)
All returns have zero mean. Each DGP produces a burn-in of 500 days (discarded), an estimation
window of 250 days, and 1,000 test days (about four trading years).

| ID | Process | Parameters | True conditional VaR |
| --- | --- | --- | --- |
| `normal_iid` | i.i.d. normal | σ = 1% daily | σ·z_c |
| `garch_normal` | GARCH(1,1), normal innovations | ω = 2·10⁻⁶, α = 0.08, β = 0.90 (unconditional σ = 1%) | σ_t·z_c |
| `garch_t5` | GARCH(1,1), Student-t innovations (ν = 5), scaled to unit variance | as above | σ_t·t_ν⁻¹(c)·√((ν−2)/ν) |
| `regime_stress` | normal, σ = 0.8%, tripled to 2.4% for test days 400–524 | — | σ_t·z_c |

`normal_iid` is the control: a correctly specified model should pass the tests at roughly their
nominal rates, which checks the harness itself.

### Methods
The production function `models.backtest.rolling_var` is called unchanged, with a 250-day window:
`historical` (empirical quantile), `parametric` (normal, sample volatility) and `ewma`
(normal, RiskMetrics λ = 0.94). Filtered historical simulation and extreme-value-theory methods
join under this same protocol when they are implemented (roadmap M1), without changing the DGPs,
seeds or metrics.

### Design
- Confidence levels: 97.5% and 99%.
- Paths: 200 per DGP. Seeds: path k of DGP d uses `numpy.random.default_rng([20261123, d, k])`.
- Forecasts are strictly out of sample: the forecast for day t uses returns up to t−1 only.

### Metrics (per DGP × method × confidence, aggregated over paths)
| Metric | Definition | Ideal |
| --- | --- | --- |
| Exception rate | exceptions / test days | 1 − c |
| Kupiec rejection rate | share of paths where Kupiec POF rejects at 5% | ≈ 5% (the test's size) |
| Independence rejection rate | share of paths where Christoffersen rejects at 5% | ≈ 5% |
| Basel zones (99% only) | zone frequencies over non-overlapping 250-day blocks | binomial expectation under a correct model (reported alongside) |
| Relative bias | mean of (VaR̂ − VaR)/VaR | 0 |
| Relative RMSE | √mean(((VaR̂ − VaR)/VaR)²) | 0 |
| Excess tick loss | mean tick loss of method ÷ that of the true VaR − 1 | 0% (the oracle is the lower bound in expectation) |

Tick loss for loss L and forecast q at level c: (c − 1{L ≤ q})·(L − q).

## 4. Benchmark B: historical market data

**Question:** how do the methods behave on real index returns, especially in crises?

- Series: daily closing levels of ^GSPC (S&P 500), ^GSPTSE (S&P/TSX Composite), ^FTSE (FTSE 100),
  ^N225 (Nikkei 225), ^HSI (Hang Seng), from 2000-01-01 to 2025-12-31, simple returns.
- Broad indices are used to avoid survivorship bias from hand-picked stocks.
- Same methods, window (250) and confidence levels as Benchmark A.
- Windows: full sample; GFC 2007-07-01 to 2009-06-30; COVID 2020-02-01 to 2020-06-30;
  rates shock 2022-01-01 to 2022-12-31. Crisis windows are scored with forecasts made from data
  before each day (no re-estimation on the crisis itself).
- Metrics: exception count vs expected, exception rate, Kupiec p-value, Christoffersen p-value,
  Basel zone for every complete 250-day block (99%), and the share of red/yellow blocks.
- Data: downloaded by the runner on the user's machine; raw prices are not committed. The runner
  records the first/last date and number of observations per series, and a hash of the data, so a
  later run can confirm it used the same snapshot.
- Caveat: banks backtest against portfolio P&L, not index returns. Index returns are a transparent,
  public stand-in.

## 5. Benchmark C: engineering

- **Performance:** median wall time of 7 repetitions (after one warm-up) for parametric,
  historical and Monte Carlo VaR (10,000 simulations) and the parametric trace, on synthetic
  portfolios of 10, 100 and 500 positions with 252 days of returns; and a 1,000-day rolling
  backtest per method. Hardware, OS, Python and numpy versions are recorded with every result.
- **Test inventory:** number of collected tests in the engine suite and whether it passes.
- **Reproducibility:** each simulated benchmark is run twice; results must be identical.

## 6. Planned benchmarks (same protocol, added at later milestones)

- **Mutation score** of `models/` (share of injected bugs caught by the test suite).
- **Trace fidelity:** share of traces that reproduce the production figure exactly.
- **Verifier recall and false-positive rate** on an adversarial set of fabricated numbers.
- **REST/MCP parity:** share of runs with identical results across interfaces.
- **New methods** (FHS, EVT, shrinkage) added to Benchmarks A and B.

## 7. Controls against misleading results

| Risk | Control |
| --- | --- |
| Choosing tests after seeing results | This protocol is fixed and versioned before running |
| Look-ahead bias | Rolling forecasts use only prior data; enforced by the production function and tested |
| Low statistical power (≈2.5 expected exceptions per year at 99%) | 200 paths × 1,000 days; 5 indices × 26 years; two confidence levels |
| Survivorship bias | Broad indices, not hand-picked stocks |
| Lucky seeds | Seeds fixed in advance and published; aggregate over many paths |
| Harness bugs | Control DGP must reproduce nominal test sizes and binomial zone frequencies |

## 8. Reporting rules

1. Every metric in §3–5 is reported for every method, including unfavourable results.
2. Results files (`benchmarks/results/*.json`) are committed with the protocol version, git commit,
   date and environment; `BENCHMARKS.md` is generated from them, never edited by hand.
3. A number may be cited (for example on a CV) only if it appears in `BENCHMARKS.md` and can be
   reproduced with the documented command.
4. Simulated results are always labelled as simulated.

## 9. How to run

```bash
pip install -r engine/requirements.txt
python benchmarks/run_simulated.py          # Benchmark A (add --quick for a smoke test)
python benchmarks/run_performance.py        # Benchmark C
python benchmarks/run_market.py             # Benchmark B (needs internet, uses yfinance)
python benchmarks/report.py                 # regenerates BENCHMARKS.md
```

## Changelog
- 1.0 (2026-11-23): initial protocol.
