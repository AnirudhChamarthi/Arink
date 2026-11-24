# Contract requests from `riskbot/core/balance_sheet`

None of these block the component; each is worked around locally.

## 1. Optional metric `liquidity_shortfall` for `q2.resilience`

**What.** Add `MetricSpec(key="liquidity_shortfall", unit=Unit.CURRENCY, optional=True, higher_is_worse=True,
description="Outflow that cannot be met even after selling all securities.")`.

**Why.** When the run exceeds all saleable assets the model records the shortfall (trace step
`liquidity_shortfall`, warning, LCR set to 0) but cannot expose it as a metric, so the comparator and reporter
cannot show how far short the bank is.

**Workaround.** Trace step + `ModelOutput.warnings`.

```diff
         MetricSpec(key="lcr_after", unit=Unit.RATIO, description="LCR after stress.", higher_is_worse=False),
+        MetricSpec(key="liquidity_shortfall", unit=Unit.CURRENCY, optional=True, higher_is_worse=True,
+                   description="Outflow that cannot be met even after selling all securities."),
     ],
```

## 2. Thresholds and severity for `q2.reverse_stress`

**What.** Add `capital_threshold`, `lcr_threshold` (same specs as `q2.resilience`) and optionally
`loss_severity` to `Q2_REVERSE_STRESS.params`.

**Why.** The reverse stress test should break the *same* target a user set for the grid; today it can only use
the resilience defaults (7%, 1.0, base severity).

**Workaround.** The model uses the `q2.resilience` defaults, read from the catalogue, and states this in the
trace assumptions and inputs.

```diff
         ParamSpec(name="tolerance", type="float", default=0.001, minimum=1e-6, maximum=0.05, ...),
+        ParamSpec(name="capital_threshold", type="float", default=0.07, minimum=0.0, maximum=0.3,
+                  description="As in q2.resilience."),
+        ParamSpec(name="lcr_threshold", type="float", default=1.0, minimum=0.0, maximum=3.0,
+                  description="As in q2.resilience."),
     ],
```
