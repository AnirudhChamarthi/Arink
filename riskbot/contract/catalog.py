"""The model catalogue: every calculation the system offers, its parameters and its outputs.

This is the linking piece of the contract.
* Core packages implement exactly these model ids, parameters, metric keys and label values.
* The planner builds variation grids from these parameter specs.
* Adapters and the UI render these specs; they never hard-code model knowledge.

Model implementations may add *optional* metrics only after a contract change.
"""

from __future__ import annotations

from .types import (
    DatasetKind,
    ExtraRun,
    GridSpec,
    MetricSpec,
    ModelSpec,
    ParamSpec,
    QuestionId,
    QuestionInfo,
    QuestionPlan,
    Unit,
)

Q1, Q2, Q3 = QuestionId.Q1, QuestionId.Q2, QuestionId.Q3

# --------------------------------------------------------------------------------------------
# Q1: market tail risk
# --------------------------------------------------------------------------------------------

Q1_METHODS = ["normal", "student_t", "historical", "fhs", "evt", "montecarlo"]
_COV_METHODS = ["normal", "student_t", "montecarlo"]

Q1_VAR = ModelSpec(
    model_id="q1.var",
    question=Q1,
    dataset_kind=DatasetKind.MARKET,
    title="Portfolio VaR and expected shortfall",
    description=(
        "Loss quantile (VaR) and expected shortfall of the portfolio over `horizon_days`, as a fraction of gross "
        "exposure, estimated from the most recent `window_days` of history. Portfolio weights are signed market "
        "value / gross exposure. Covariance methods (normal, student_t, montecarlo) use the asset covariance; "
        "historical, fhs and evt work on the historical portfolio return series. Multi-day: sqrt(h) scaling of "
        "the 1-day figure except montecarlo, which simulates N(h*mu, h*Sigma). Optional block bootstrap gives a "
        "95% interval for VaR. The backtest always rolls the same method with a 250-day window over the whole "
        "history at 1-day horizon and the same confidence (Kupiec POF, Christoffersen independence, Basel zone on "
        "the last 250 forecasts)."
    ),
    params=[
        ParamSpec(name="method", type="str", default="normal", choices=Q1_METHODS,
                  description="normal: Gaussian; student_t: Student-t scaled to unit variance; historical: empirical "
                              "quantile; fhs: GARCH(1,1)-filtered historical simulation; evt: peaks-over-threshold "
                              "generalized Pareto tail; montecarlo: multivariate normal simulation."),
        ParamSpec(name="confidence", type="float", default=0.99, minimum=0.9, maximum=0.999,
                  description="VaR confidence level."),
        ParamSpec(name="horizon_days", type="int", default=5, minimum=1, maximum=20, description="Horizon in trading days."),
        ParamSpec(name="window_days", type="int", default=250, choices=[250, 500, 750],
                  description="Most recent observations used for estimation; if fewer exist, all are used with a warning."),
        ParamSpec(name="covariance", type="str", default="sample", choices=["sample", "ledoit_wolf"],
                  applies_when={"method": _COV_METHODS},
                  description="Sample covariance or Ledoit-Wolf shrinkage towards constant correlation."),
        ParamSpec(name="t_dof", type="float", default=5.0, minimum=2.5, maximum=100.0,
                  applies_when={"method": ["student_t"]}, description="Degrees of freedom for student_t."),
        ParamSpec(name="evt_threshold_quantile", type="float", default=0.90, minimum=0.8, maximum=0.97,
                  applies_when={"method": ["evt"]}, description="Loss quantile used as the POT threshold u."),
        ParamSpec(name="n_sims", type="int", default=20000, minimum=1000, maximum=200000,
                  applies_when={"method": ["montecarlo"]}, description="Monte Carlo paths."),
        ParamSpec(name="bootstrap", type="int", default=0, minimum=0, maximum=1000,
                  description="Block-bootstrap resamples for a 95% VaR interval; 0 disables."),
        ParamSpec(name="backtest", type="bool", default=True, description="Run the rolling backtest."),
    ],
    metrics=[
        MetricSpec(key="var", unit=Unit.FRACTION_OF_GROSS, description="Value at Risk.", higher_is_worse=True),
        MetricSpec(key="es", unit=Unit.FRACTION_OF_GROSS, description="Expected shortfall.", higher_is_worse=True),
        MetricSpec(key="var_amount", unit=Unit.CURRENCY, description="VaR x gross exposure.", higher_is_worse=True),
        MetricSpec(key="es_amount", unit=Unit.CURRENCY, description="ES x gross exposure.", higher_is_worse=True),
        MetricSpec(key="gross_exposure", unit=Unit.CURRENCY, description="Sum of |market value|."),
        MetricSpec(key="var_ci_low", unit=Unit.FRACTION_OF_GROSS, description="Bootstrap 2.5% VaR.", optional=True),
        MetricSpec(key="var_ci_high", unit=Unit.FRACTION_OF_GROSS, description="Bootstrap 97.5% VaR.", optional=True),
        MetricSpec(key="backtest_days", unit=Unit.COUNT, description="Out-of-sample backtest days.", optional=True),
        MetricSpec(key="backtest_exceptions", unit=Unit.COUNT, description="Days with loss > VaR.", optional=True,
                   higher_is_worse=True),
        MetricSpec(key="backtest_exception_rate", unit=Unit.FRACTION, description="Exceptions / days.", optional=True),
        MetricSpec(key="kupiec_p", unit=Unit.PROBABILITY, description="Kupiec POF p-value.", optional=True),
        MetricSpec(key="independence_p", unit=Unit.PROBABILITY, description="Christoffersen p-value.", optional=True),
    ],
    labels={
        "basel_zone": ["green", "yellow", "red", "n/a"],
        "backtest_verdict": ["pass", "fail", "n/a"],  # pass iff kupiec_p >= 0.05 and independence_p >= 0.05
    },
    method_param="method",
    pass_label="backtest_verdict",
)

Q1_DATA_QUALITY = ModelSpec(
    model_id="q1.data_quality",
    question=Q1,
    dataset_kind=DatasetKind.MARKET,
    title="Market data quality",
    description="Missing values, stale series, outliers (|r - rolling median| > 10 x 1.4826 x MAD over a centred "
                "63-day window, at least 20 values), history length; one finding per issue.",
    params=[ParamSpec(name="stale_days", type="int", default=5, minimum=2, maximum=30,
                      description="A run of this many identical consecutive returns of 0 counts as stale.")],
    metrics=[
        MetricSpec(key="n_positions", unit=Unit.COUNT, description="Positions."),
        MetricSpec(key="history_days", unit=Unit.DAYS, description="Length of the return history."),
        MetricSpec(key="missing_share", unit=Unit.FRACTION, description="Missing return values / all values.",
                   higher_is_worse=True),
        MetricSpec(key="stale_series", unit=Unit.COUNT, description="Series with a stale run.", higher_is_worse=True),
        MetricSpec(key="outlier_count", unit=Unit.COUNT, description="Outlier returns.", higher_is_worse=True),
    ],
    labels={"quality": ["good", "fair", "poor"]},
)

# --------------------------------------------------------------------------------------------
# Q2: balance-sheet resilience
# --------------------------------------------------------------------------------------------

Q2_RESILIENCE = ModelSpec(
    model_id="q2.resilience",
    question=Q2,
    dataset_kind=DatasetKind.BALANCE_SHEET,
    title="Rate shock plus deposit run",
    description=(
        "Instantaneous parallel rate shock and a 30-day deposit run. EVE change from duration/convexity "
        "(cash-flow revaluation where duration is missing), net of pay-fixed swap hedges. 12-month NII change from "
        "repricing gaps with deposit betas. Credit loss = sum EAD x LGD x stressed PD, stressed PD by Vasicek at "
        "q = 0.90 (base) or 0.99 (adverse). Outflows met from cash, then HQLA, then by selling AFS then HTM "
        "securities at a fire-sale price p = exp(-impact x share sold), solved as a fixed point. Unrealised "
        "losses on HTM count against capital only under mark_to_market; realised losses always do. Pass iff "
        "capital ratio >= capital_threshold and LCR >= lcr_threshold after stress. Thresholds are illustrative."
    ),
    params=[
        ParamSpec(name="rate_shock_bp", type="int", default=200, minimum=-400, maximum=600,
                  description="Parallel shift of the yield curve in basis points."),
        ParamSpec(name="run_speed", type="str", default="slow", choices=["none", "slow", "fast"],
                  description="Which 30-day run-off rates apply to deposits."),
        ParamSpec(name="loss_severity", type="str", default="base", choices=["base", "adverse"],
                  description="Vasicek quantile for stressed PD: base 0.90, adverse 0.99."),
        ParamSpec(name="htm_treatment", type="str", default="at_cost", choices=["at_cost", "mark_to_market"],
                  description="Whether unrealised HTM losses reduce capital."),
        ParamSpec(name="capital_threshold", type="float", default=0.07, minimum=0.0, maximum=0.3,
                  description="Minimum CET1 / RWA after stress (illustrative)."),
        ParamSpec(name="lcr_threshold", type="float", default=1.0, minimum=0.0, maximum=3.0,
                  description="Minimum LCR after stress (illustrative)."),
        ParamSpec(name="fire_sale_impact", type="float", default=0.05, minimum=0.0, maximum=1.0,
                  description="Price impact lambda: price = exp(-lambda x fraction of saleable securities sold)."),
    ],
    metrics=[
        MetricSpec(key="delta_eve", unit=Unit.CURRENCY, description="Change in economic value of equity."),
        MetricSpec(key="delta_eve_pct_cet1", unit=Unit.FRACTION, description="Delta EVE / CET1."),
        MetricSpec(key="delta_nii_12m", unit=Unit.CURRENCY, description="12-month NII change."),
        MetricSpec(key="credit_loss", unit=Unit.CURRENCY, description="Stressed credit loss.", higher_is_worse=True),
        MetricSpec(key="unrealised_securities_loss", unit=Unit.CURRENCY, description="Mark-to-market loss on securities.",
                   higher_is_worse=True),
        MetricSpec(key="deposit_outflow", unit=Unit.CURRENCY, description="30-day deposit outflow.", higher_is_worse=True),
        MetricSpec(key="fire_sale_loss", unit=Unit.CURRENCY, description="Realised loss from forced sales.",
                   higher_is_worse=True),
        MetricSpec(key="cet1_after", unit=Unit.CURRENCY, description="CET1 after all losses."),
        MetricSpec(key="capital_ratio_before", unit=Unit.FRACTION, description="CET1 / RWA before stress."),
        MetricSpec(key="capital_ratio_after", unit=Unit.FRACTION, description="CET1 / RWA after stress.",
                   higher_is_worse=False),
        MetricSpec(key="lcr_before", unit=Unit.RATIO, description="LCR before stress."),
        MetricSpec(key="lcr_after", unit=Unit.RATIO, description="LCR after stress.", higher_is_worse=False),
    ],
    labels={"verdict": ["pass", "fail"], "binding_constraint": ["none", "capital", "liquidity", "both"]},
    pass_label="verdict",
)

Q2_REVERSE_STRESS = ModelSpec(
    model_id="q2.reverse_stress",
    question=Q2,
    dataset_kind=DatasetKind.BALANCE_SHEET,
    title="Reverse stress test",
    description=(
        "Bisection on the q2.resilience model. breakeven_deposit_outflow: smallest uniform 30-day outflow fraction "
        "of all deposits (0..1) that breaches the target constraint at `rate_shock_bp`. breakeven_rate_shock_bp: "
        "smallest parallel shock (0..1000 bp) that breaches the target with run_speed='slow'. A metric is omitted "
        "if no breach occurs within its range. Monotonicity is checked and reported as a warning if violated."
    ),
    params=[
        ParamSpec(name="target", type="str", default="capital", choices=["capital", "liquidity"],
                  description="Which constraint to break."),
        ParamSpec(name="rate_shock_bp", type="int", default=200, minimum=-400, maximum=600,
                  description="Rate shock held fixed while searching the outflow."),
        ParamSpec(name="htm_treatment", type="str", default="at_cost", choices=["at_cost", "mark_to_market"],
                  description="As in q2.resilience."),
        ParamSpec(name="tolerance", type="float", default=0.001, minimum=1e-6, maximum=0.05,
                  description="Bisection tolerance (fraction for outflow; x1000 bp for rates)."),
    ],
    metrics=[
        MetricSpec(key="breakeven_deposit_outflow", unit=Unit.FRACTION, optional=True, higher_is_worse=False,
                   description="Smallest deposit outflow that breaches the target."),
        MetricSpec(key="breakeven_rate_shock_bp", unit=Unit.BASIS_POINTS, optional=True, higher_is_worse=False,
                   description="Smallest rate shock that breaches the target."),
    ],
    labels={"outflow_found": ["yes", "no"], "rate_found": ["yes", "no"]},
)

Q2_DATA_QUALITY = ModelSpec(
    model_id="q2.data_quality",
    question=Q2,
    dataset_kind=DatasetKind.BALANCE_SHEET,
    title="Balance-sheet data quality and structure",
    description="Reconciliation and structural indicators used by the Q2 rubric.",
    params=[],
    metrics=[
        MetricSpec(key="loan_reconciliation_gap", unit=Unit.FRACTION, higher_is_worse=True,
                   description="|sum of loan-pool EAD - loans book value| / loans book value."),
        MetricSpec(key="uninsured_deposit_share", unit=Unit.FRACTION, higher_is_worse=True,
                   description="Uninsured deposits / all deposits."),
        MetricSpec(key="largest_segment_share", unit=Unit.FRACTION, higher_is_worse=True,
                   description="Largest deposit segment / all deposits."),
        MetricSpec(key="hqla_share", unit=Unit.FRACTION, description="HQLA / total assets."),
        MetricSpec(key="duration_gap_years", unit=Unit.YEARS, higher_is_worse=True,
                   description="Asset duration - (liabilities / assets) x liability duration."),
        MetricSpec(key="hedge_ratio", unit=Unit.FRACTION, description="Swap notional / fixed-rate securities."),
        MetricSpec(key="htm_share_of_securities", unit=Unit.FRACTION, description="HTM / all securities."),
    ],
    labels={"quality": ["good", "fair", "poor"]},
)

# --------------------------------------------------------------------------------------------
# Q3: transition risk
# --------------------------------------------------------------------------------------------

Q3_TRANSITION = ModelSpec(
    model_id="q3.transition",
    question=Q3,
    dataset_kind=DatasetKind.CLIMATE,
    title="Transition-risk valuation shock",
    description=(
        "Illustrative NGFS-style scenarios set a carbon-price path; price_path scales it (low 0.5x, central 1x, "
        "high 2x). Annual carbon cost = emissions x price x (1 - sector pass-through); value shock = -(PV of cost "
        "over horizon) / EVIC, capped at -100%, applied to long market value. Missing or estimated emissions are "
        "imputed per `missing_data` (sector-average intensity, its 75th percentile, or excluded) and sampled "
        "log-normally with spread increasing in data_quality; loss quantiles come from `n_sims` draws. Financed "
        "emissions use attribution MV / EVIC. Alignment ratio = portfolio intensity / budget-pathway intensity."
    ),
    params=[
        ParamSpec(name="scenario", type="str", default="orderly", choices=["orderly", "disorderly", "hot_house"],
                  description="Carbon-price scenario family (illustrative, NGFS-style)."),
        ParamSpec(name="price_path", type="str", default="central", choices=["low", "central", "high"],
                  description="Multiplier on the scenario's carbon-price path."),
        ParamSpec(name="missing_data", type="str", default="sector_average",
                  choices=["sector_average", "conservative", "exclude"],
                  description="Treatment of missing emissions."),
        ParamSpec(name="include_scope3", type="bool", default=False, description="Add scope 3 where available."),
        ParamSpec(name="horizon_years", type="int", default=10, minimum=1, maximum=30, description="Cost horizon."),
        ParamSpec(name="n_sims", type="int", default=2000, minimum=100, maximum=20000, description="Uncertainty draws."),
    ],
    metrics=[
        MetricSpec(key="loss_pct", unit=Unit.FRACTION, description="Median loss / long market value.", higher_is_worse=True),
        MetricSpec(key="loss_p05", unit=Unit.FRACTION, description="5th percentile of loss.", higher_is_worse=True),
        MetricSpec(key="loss_p95", unit=Unit.FRACTION, description="95th percentile of loss.", higher_is_worse=True),
        MetricSpec(key="loss_amount", unit=Unit.CURRENCY, description="Median loss in currency.", higher_is_worse=True),
        MetricSpec(key="waci", unit=Unit.TCO2E_PER_MUSD, description="Weighted average carbon intensity.",
                   higher_is_worse=True),
        MetricSpec(key="financed_emissions", unit=Unit.TCO2E, description="Attributed emissions.", higher_is_worse=True),
        MetricSpec(key="carbon_price_end", unit=Unit.CURRENCY, description="Carbon price per tonne at the horizon."),
        MetricSpec(key="alignment_ratio", unit=Unit.RATIO, description="Intensity / pathway intensity.",
                   higher_is_worse=True),
        MetricSpec(key="estimated_share", unit=Unit.FRACTION, description="Share of financed emissions imputed.",
                   higher_is_worse=True),
    ],
    labels={"exposure_level": ["low", "moderate", "high"]},
    method_param="missing_data",
)

Q3_DATA_QUALITY = ModelSpec(
    model_id="q3.data_quality",
    question=Q3,
    dataset_kind=DatasetKind.CLIMATE,
    title="Climate data quality",
    description="Coverage and quality of emissions data, weighted by market value.",
    params=[ParamSpec(name="stale_years", type="int", default=2, minimum=0, maximum=10,
                      description="Emissions older than as_of year minus this are stale.")],
    metrics=[
        MetricSpec(key="coverage_scope12", unit=Unit.FRACTION, description="MV share with scope 1 and 2."),
        MetricSpec(key="coverage_scope3", unit=Unit.FRACTION, description="MV share with scope 3."),
        MetricSpec(key="mean_data_quality", unit=Unit.RATIO, description="MV-weighted data-quality score (1 best).",
                   higher_is_worse=True),
        MetricSpec(key="stale_share", unit=Unit.FRACTION, description="MV share with stale emissions.",
                   higher_is_worse=True),
        MetricSpec(key="controversy_share", unit=Unit.FRACTION, description="MV share with controversy flags.",
                   higher_is_worse=True),
    ],
    labels={"quality": ["good", "fair", "poor"]},
)

MODEL_SPECS: dict[str, ModelSpec] = {
    s.model_id: s
    for s in (Q1_VAR, Q1_DATA_QUALITY, Q2_RESILIENCE, Q2_REVERSE_STRESS, Q2_DATA_QUALITY, Q3_TRANSITION, Q3_DATA_QUALITY)
}

# --------------------------------------------------------------------------------------------
# Questions and default plans
# --------------------------------------------------------------------------------------------

DEFAULT_PLANS: dict[QuestionId, QuestionPlan] = {
    Q1: QuestionPlan(
        question=Q1,
        grid=GridSpec(
            model_id="q1.var",
            dimensions={"method": Q1_METHODS, "window_days": [250, 750], "covariance": ["sample", "ledoit_wolf"]},
            fixed={"confidence": 0.99, "horizon_days": 5, "bootstrap": 200, "backtest": True},
        ),
        extras=[ExtraRun(model_id="q1.data_quality")],
    ),
    Q2: QuestionPlan(
        question=Q2,
        grid=GridSpec(
            model_id="q2.resilience",
            dimensions={
                "rate_shock_bp": [-200, 100, 200, 300],
                "run_speed": ["slow", "fast"],
                "loss_severity": ["base", "adverse"],
                "htm_treatment": ["at_cost", "mark_to_market"],
            },
        ),
        extras=[
            ExtraRun(model_id="q2.reverse_stress", params={"target": "capital"}),
            ExtraRun(model_id="q2.reverse_stress", params={"target": "liquidity"}),
            ExtraRun(model_id="q2.data_quality"),
        ],
    ),
    Q3: QuestionPlan(
        question=Q3,
        grid=GridSpec(
            model_id="q3.transition",
            dimensions={
                "scenario": ["orderly", "disorderly", "hot_house"],
                "price_path": ["low", "central", "high"],
                "missing_data": ["sector_average", "conservative", "exclude"],
            },
            fixed={"n_sims": 2000, "include_scope3": False, "horizon_years": 10},
        ),
        extras=[ExtraRun(model_id="q3.data_quality")],
    ),
}

QUESTIONS: dict[QuestionId, QuestionInfo] = {
    Q1: QuestionInfo(
        question=Q1, dataset_kind=DatasetKind.MARKET, default_plan=DEFAULT_PLANS[Q1],
        title="How much could this portfolio lose in a bad week, and how far should we trust that number?",
        description="Market tail risk under six methods, two windows and two covariance estimators, each backtested.",
    ),
    Q2: QuestionInfo(
        question=Q2, dataset_kind=DatasetKind.BALANCE_SHEET, default_plan=DEFAULT_PLANS[Q2],
        title="Could this bank-like balance sheet survive a rate shock combined with a deposit run?",
        description="Interest-rate, credit and liquidity stress with fire sales and a reverse stress test.",
    ),
    Q3: QuestionInfo(
        question=Q3, dataset_kind=DatasetKind.CLIMATE, default_plan=DEFAULT_PLANS[Q3],
        title="How exposed is this portfolio to the low-carbon transition, and how reliable is the data?",
        description="Carbon-price scenarios with uncertainty from missing emissions data.",
    ),
}

# Hard limits enforced by every entry point (adapters validate; services re-check).
LIMITS = {
    "max_positions": 1000,
    "max_history_days": 5000,
    "max_balance_sheet_items": 2000,
    "max_holdings": 2000,
    "max_variations": 1000,
}
