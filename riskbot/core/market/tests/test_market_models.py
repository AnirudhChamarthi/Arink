"""Model-level tests for q1.var and q1.data_quality: conformance, determinism, traces, edge cases."""

import datetime as dt
import itertools
import math

import numpy as np
import pytest

from riskbot.contract import catalog
from riskbot.contract.conformance import check_output, resolve_params
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.ports import Model
from riskbot.contract.types import MarketDataset, MarketPosition, QuestionId
from riskbot.core.market import estimators as E
from riskbot.core.market import models, sample_dataset
from riskbot.core.market.var_model import VarModel

SEED = 20261123


@pytest.fixture(scope="module")
def ds():
    return sample_dataset()


def _plan_variations():
    plan = catalog.DEFAULT_PLANS[QuestionId.Q1]
    dims = plan.grid.dimensions
    out = {}
    for combo in itertools.product(*dims.values()):
        p = resolve_params(catalog.Q1_VAR, {**plan.grid.fixed, **dict(zip(dims, combo))})
        out[tuple(sorted(p.items()))] = p
    return list(out.values())


@pytest.fixture(scope="module")
def plan_outputs(ds):
    var = VarModel()
    return [(p, var.run(ds, p, SEED)) for p in _plan_variations()]


def _dataset(R, tickers=None, qty=None, start=dt.date(2020, 1, 1), cash=0.0):
    R = np.asarray(R, dtype=float)
    n, k = R.shape
    tickers = tickers or [f"T{i}" for i in range(k)]
    qty = qty if qty is not None else [100.0] * k
    dates = [start + dt.timedelta(days=i) for i in range(n)]
    pos = [MarketPosition(ticker=t, quantity=q, price=10.0) for t, q in zip(tickers, qty)]
    if cash:
        pos.append(MarketPosition(ticker="CASH", asset_class="cash", quantity=cash, price=1.0))
    rets = {t: [None if np.isnan(v) else float(v) for v in R[:, j]] for j, t in enumerate(tickers)}
    return MarketDataset(name="test", as_of=dates[-1], synthetic=True, positions=pos, dates=dates, returns=rets)


# --------------------------------------------------------------------------------------------
# Package interface and sample dataset
# --------------------------------------------------------------------------------------------


def test_models_export_specs():
    ms = models()
    assert [m.spec for m in ms] == [catalog.Q1_VAR, catalog.Q1_DATA_QUALITY]
    assert all(isinstance(m, Model) for m in ms)


def test_sample_dataset_design(ds):
    assert ds.synthetic and ds.kind == "market"
    assert 12 <= len(ds.positions) <= 15 <= catalog.LIMITS["max_positions"]
    assert sum(p.quantity < 0 for p in ds.positions) >= 2
    assert sum(p.asset_class == "cash" for p in ds.positions) == 1
    assert len({p.sector for p in ds.positions if p.sector}) >= 6
    assert 760 <= len(ds.dates) <= 800 and ds.dates[-1] == dt.date(2026, 10, 30) == ds.as_of
    assert all(d.weekday() < 5 for d in ds.dates)
    flat = [v for s in ds.returns.values() for v in s]
    assert 0 < sum(v is None for v in flat) <= 20
    # correlations in roughly the designed 0.2-0.6 band (outside the stress window)
    full = np.array([[np.nan if v is None else v for v in s] for s in ds.returns.values()]).T
    R = full[300:]
    R = R[~np.isnan(R).any(axis=1)]
    C = np.corrcoef(R, rowvar=False)
    off = C[~np.eye(len(C), dtype=bool)]
    assert 0.1 < off.min() and off.max() < 0.7 and 0.2 < off.mean() < 0.5
    # stress episode: much higher volatility inside the oldest 500 days
    assert np.nanstd(full[150:210]) > 2.0 * np.nanstd(full[-250:])


def test_sample_dataset_deterministic():
    assert sample_dataset(0) == sample_dataset(0)
    assert sample_dataset(0) != sample_dataset(1)


# --------------------------------------------------------------------------------------------
# Conformance of every default-plan variation
# --------------------------------------------------------------------------------------------


def test_default_plan_has_eighteen_variations():
    assert len(_plan_variations()) == 18


def test_every_default_plan_variation_conforms(plan_outputs):
    for p, out in plan_outputs:
        assert check_output(catalog.Q1_VAR, out) == [], p
        assert out.params == p
        for k in ("var_ci_low", "var_ci_high", "backtest_days", "kupiec_p", "independence_p"):
            assert k in out.metrics, (p, k)
        assert out.labels["basel_zone"] in ("green", "yellow", "red")
        assert out.labels["backtest_verdict"] in ("pass", "fail")
        assert out.metrics["backtest_days"].value == 774 - 250  # 780 dates - 6 dropped for missing values
        assert any(f.check == "missing_returns" and f.count == 6 for f in out.findings)
        assert out.traces[0].trace_id.startswith("q1.var-")


def test_es_at_least_var_and_ci_brackets(plan_outputs):
    for p, out in plan_outputs:
        m = {k: v.value for k, v in out.metrics.items()}
        assert m["es"] >= m["var"] > 0, p
        assert m["var_ci_low"] <= m["var_ci_high"]
        assert m["var_amount"] == pytest.approx(m["var"] * m["gross_exposure"])
        assert m["es_amount"] == pytest.approx(m["es"] * m["gross_exposure"])


def test_windows_differ_clearly_on_sample(plan_outputs):
    by = {(p["method"], p["window_days"], p.get("covariance")): o.metrics["var"].value for p, o in plan_outputs}
    for method in ("normal", "historical", "student_t"):
        cov = None if method == "historical" else "sample"
        assert by[(method, 750, cov)] > 1.4 * by[(method, 250, cov)]


def test_trace_rederives_normal_var(ds):
    out = VarModel().run(ds, {"method": "normal", "bootstrap": 0, "backtest": False}, SEED)
    steps = {s.id: s for s in out.traces[0].steps}
    w = {r["ticker"]: r["weight"] for r in steps["weights"].table}
    cov = steps["covariance"].table
    tick = [r["ticker"] for r in cov]
    S = np.array([[r[f"cov_{t}"] for t in tick] for r in cov])
    wv = np.array([w[t] for t in tick])
    sigma = math.sqrt(wv @ S @ wv)
    assert sigma == pytest.approx(steps["portfolio_sigma"].value, rel=1e-12)
    assert out.metrics["var"].value == pytest.approx(steps["quantile"].value * sigma * math.sqrt(5), rel=1e-12)
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0)


def test_trace_contains_method_specific_steps(plan_outputs):
    need = {"normal": {"covariance", "portfolio_sigma", "quantile"},
            "student_t": {"quantile", "variance_scale"},
            "historical": {"es_1d"},
            "fhs": {"garch_fit", "sigma_forecast", "standardized_residuals"},
            "evt": {"threshold", "exceedances", "gpd_shape", "gpd_scale"},
            "montecarlo": {"mean_vector", "simulation"}}
    common = {"weights", "gross_exposure", "window", "portfolio_returns", "horizon_scaling", "var", "es",
              "var_amount", "es_amount", "bootstrap", "backtest_days", "kupiec_lr", "independence_lr", "basel_zone"}
    for p, out in plan_outputs:
        ids = {s.id for s in out.traces[0].steps}
        assert need[p["method"]] | common <= ids, p
        if p.get("covariance") == "ledoit_wolf":
            d = next(s for s in out.traces[0].steps if s.id == "shrinkage_intensity").value
            assert 0 <= d <= 1


# --------------------------------------------------------------------------------------------
# Scaling, method properties at model level
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["normal", "student_t", "historical", "fhs", "evt"])
def test_sqrt_h_scaling(ds, method):
    base = {"method": method, "bootstrap": 0, "backtest": False, "window_days": 750}
    v1 = VarModel().run(ds, {**base, "horizon_days": 1}, SEED).metrics
    v9 = VarModel().run(ds, {**base, "horizon_days": 9}, SEED).metrics
    assert v9["var"].value == pytest.approx(3 * v1["var"].value, rel=1e-12)
    assert v9["es"].value == pytest.approx(3 * v1["es"].value, rel=1e-12)


def test_montecarlo_close_to_normal_on_sample_with_many_paths(ds):
    p = {"bootstrap": 0, "backtest": False, "covariance": "sample"}
    mc = VarModel().run(ds, {**p, "method": "montecarlo", "n_sims": 200000}, SEED)
    steps = {s.id: s.value for s in mc.traces[0].steps}
    # analytic h-day normal quantile with the sample mean: -h w'mu + z_c sqrt(h) sigma_p
    analytic = -5 * steps["mean_vector"] + 2.3263478740408408 * math.sqrt(5) * steps["portfolio_sigma"]
    assert mc.metrics["var"].value == pytest.approx(analytic, rel=0.01)
    nm = VarModel().run(ds, {**p, "method": "normal"}, SEED)
    assert nm.metrics["var"].value == pytest.approx(analytic + 5 * steps["mean_vector"], rel=1e-12)


def test_historical_model_equals_numpy_quantile():
    rng = np.random.default_rng(0)
    R = rng.standard_t(4, size=(400, 2)) * 0.01
    ds = _dataset(R, qty=[100.0, -50.0])
    out = VarModel().run(ds, {"method": "historical", "horizon_days": 1, "bootstrap": 0, "backtest": False}, 1)
    w = np.array([1000.0, -500.0]) / 1500.0
    assert out.metrics["var"].value == np.quantile(-(R[-250:] @ w), 0.99)


def test_cash_dilutes_risk_proportionally():
    R = np.random.default_rng(2).standard_normal((300, 2)) * 0.01
    p = {"method": "normal", "bootstrap": 0, "backtest": False}
    a = VarModel().run(_dataset(R), p, 1).metrics
    b = VarModel().run(_dataset(R, cash=2000.0), p, 1).metrics  # gross 2000 -> 4000
    assert b["var"].value == pytest.approx(a["var"].value / 2, rel=1e-12)
    assert b["var_amount"].value == pytest.approx(a["var_amount"].value, rel=1e-12)


# --------------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["montecarlo", "fhs"])
def test_determinism_same_seed_identical_output(ds, method):
    p = {"method": method, "bootstrap": 30, "backtest": False, "n_sims": 2000} if method == "montecarlo" else \
        {"method": method, "bootstrap": 10, "backtest": False}
    a = VarModel().run(ds, p, 7)
    b = VarModel().run(ds, p, 7)
    assert a.model_dump() == b.model_dump()
    assert a.traces[0].trace_id == b.traces[0].trace_id
    c = VarModel().run(ds, p, 8)
    assert c.traces[0].trace_id != a.traces[0].trace_id
    if method == "montecarlo":
        assert c.metrics["var"].value != a.metrics["var"].value


# --------------------------------------------------------------------------------------------
# Edge cases, warnings and validation
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("q", [QuestionId.Q2, QuestionId.Q3])
def test_wrong_dataset_kind_raises(q):
    for m in models():
        with pytest.raises(ValidationFailed):
            m.run(fake_dataset(q), {}, 1)


def test_too_little_history_raises():
    R = np.random.default_rng(0).standard_normal((20, 2)) * 0.01
    with pytest.raises(ValidationFailed, match="observations"):
        VarModel().run(_dataset(R), {}, 1)


def test_evt_too_few_exceedances_raises():
    R = np.random.default_rng(0).standard_normal((150, 2)) * 0.01
    with pytest.raises(ValidationFailed, match="exceedances"):
        VarModel().run(_dataset(R), {"method": "evt", "backtest": False}, 1)


def test_unknown_param_raises(ds):
    with pytest.raises(ValidationFailed):
        VarModel().run(ds, {"nope": 1}, 1)


def test_short_history_window_warning_and_backtest_na():
    R = np.random.default_rng(3).standard_normal((120, 3)) * 0.01
    out = VarModel().run(_dataset(R), {"method": "normal", "window_days": 250}, 1)
    assert check_output(catalog.Q1_VAR, out) == []
    assert out.labels == {"basel_zone": "n/a", "backtest_verdict": "n/a"}
    assert "backtest_days" not in out.metrics and "kupiec_p" not in out.metrics
    assert any("Backtest skipped" in w for w in out.warnings)
    assert any("all of them are used" in w for w in out.warnings)
    assert any(f.check == "short_window" for f in out.findings)


def test_backtest_false_gives_na_without_warning(ds):
    out = VarModel().run(ds, {"method": "historical", "backtest": False}, 1)
    assert out.labels == {"basel_zone": "n/a", "backtest_verdict": "n/a"}
    assert not any(k.startswith("backtest") for k in out.metrics)
    assert not any("Backtest" in w for w in out.warnings)
    assert check_output(catalog.Q1_VAR, out) == []


def test_backtest_detects_underestimated_risk():
    # volatility doubles in the second half: a 250-day normal VaR is too low right after the break
    rng = np.random.default_rng(9)
    R = np.concatenate([rng.standard_normal((400, 1)) * 0.005, rng.standard_normal((200, 1)) * 0.02])
    out = VarModel().run(_dataset(R), {"method": "normal", "horizon_days": 1}, 1)
    assert out.labels["backtest_verdict"] == "fail"
    assert out.labels["basel_zone"] == "red"
    assert out.metrics["backtest_exception_rate"].value > 0.05


def test_fhs_falls_back_to_ewma_with_warning(ds, monkeypatch):
    monkeypatch.setattr(E, "fit_garch", lambda x, starting=None: E.GarchFit(float("nan"), float("nan"),
                                                                             float("nan"), False, None, "forced"))
    out = VarModel().run(ds, {"method": "fhs", "bootstrap": 5}, SEED)
    assert check_output(catalog.Q1_VAR, out) == []
    assert any("EWMA" in w for w in out.warnings)
    assert out.metrics["es"].value >= out.metrics["var"].value > 0


def test_dict_dataset_accepted(ds):
    out = VarModel().run(ds.model_dump(mode="json"), {"method": "normal", "bootstrap": 0, "backtest": False}, 1)
    ref = VarModel().run(ds, {"method": "normal", "bootstrap": 0, "backtest": False}, 1)
    assert out.metrics["var"].value == ref.metrics["var"].value
