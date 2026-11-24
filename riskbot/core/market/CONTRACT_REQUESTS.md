# Contract requests from `riskbot/core/market`

Nothing here blocks the component. The implementation follows the current contract (2.0.0) exactly;
each item below is a suggestion with a workaround already in place.

## 1. Outlier rule for `q1.data_quality`: use a scaled MAD

**What.** `catalog.Q1_DATA_QUALITY.description` says "outliers (|r| > 8 MAD)". The implementation uses
`|r - median| > 8 * MAD` with the raw MAD, as the description says.

**Why.** For Gaussian data the raw MAD is 0.674 sigma, so 8 raw MADs is only about 5.4 sigma. On fat-tailed
GARCH returns with a stress episode (the sample dataset) this flags about 200 genuine stress-period returns
as "outliers". That turns the check into a stress-period detector instead of a bad-tick detector, and every
series gets a warning. With the usual consistency factor (MAD x 1.4826, so 8 robust sigmas, about 11.9 raw
MADs) only real data errors would be flagged.

**Proposed diff** (catalog.py):

```diff
-    description="Missing values, stale series, outliers (|r| > 8 MAD), history length; one finding per issue.",
+    description="Missing values, stale series, outliers (|r - median| > 8 x 1.4826 x MAD), history length; "
+                "one finding per issue.",
```

The implementation change is one constant (`OUTLIER_MADS` in `data_quality.py`).

## 2. Backtest window independent of `window_days`

**What.** The catalogue says the backtest always rolls a 250-day window. So the backtest metrics and both
labels are the same for `window_days = 250` and `750`. The comparator can therefore never report a
`backtest_verdict` flip along the `window_days` dimension.

**Why it matters.** Reviewers may read "the 750-day VaR passes the backtest" as evidence about the 750-day
estimator, but it is the 250-day estimator's record. The trace says this in the `backtest_days` note.

**Option** (not urgent): add a parameter `backtest_window` with choices `["250", "same_as_window"]`, default
`"250"`, so the current behaviour is unchanged.
