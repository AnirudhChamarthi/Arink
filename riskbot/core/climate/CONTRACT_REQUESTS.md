# Contract requests from `riskbot/core/climate`

## 1. State the units of `ClimateHolding.revenue`, `evic` and `market_value`

**What.** `types.ClimateHolding` gives no units for `revenue`, `evic` or `market_value`; the WACI metric
unit is `tCO2e_per_musd`, and the component brief calls the field `revenue_musd`.

**Why.** WACI (E / revenue in USD million) and the value shock (PV of carbon cost in currency / EVIC) need
consistent units. If revenue were already in USD millions while EVIC is in currency units, WACI would be
off by 10^6. `fakes.fake_dataset(Q3)` (revenue=20000, evic=50000, scope1=100000) is consistent with
either reading.

**Workaround (implemented).** All monetary fields are read as currency units (the dataset's `currency`,
assumed USD for carbon prices); revenue is divided by 10^6 for intensities. Documented in README.md and in
every trace's assumptions.

**Proposed diff** (`riskbot/contract/types.py`):

```diff
-    market_value: float = Field(description="Signed; shorts excluded from financed emissions.")
-    evic: float = Field(gt=0, description="Enterprise value including cash.")
-    revenue: float = Field(gt=0)
+    market_value: float = Field(description="Signed, in dataset currency units; shorts excluded from financed emissions.")
+    evic: float = Field(gt=0, description="Enterprise value including cash, in dataset currency units.")
+    revenue: float = Field(gt=0, description="Annual revenue in dataset currency units (not millions).")
```

## 2. (Optional) expose the deterministic central loss as an optional metric

**What.** Add `MetricSpec(key="loss_central", unit=Unit.FRACTION, optional=True, higher_is_worse=True,
description="Deterministic loss with emissions at point estimates (no uncertainty).")` to `Q3_TRANSITION`.

**Why.** The log-normal factor is mean-preserving, so its median is below 1 and the Monte Carlo median
`loss_pct` sits slightly below the point-estimate loss. Reviewers often ask for the point estimate.

**Workaround (implemented).** The value is in trace step `central_loss` (and the `loss_pct` step table)
but is not a metric, because the catalogue forbids undeclared metrics.
