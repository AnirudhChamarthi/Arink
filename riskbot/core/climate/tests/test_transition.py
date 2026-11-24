"""Independent oracles for q3.transition (hand-computed values, closed forms and properties)."""

from __future__ import annotations

import datetime as dt
import itertools
import math

import numpy as np
import pytest

from riskbot.contract import catalog
from riskbot.contract.conformance import check_output
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.types import ClimateHolding, ClimatePortfolio
from riskbot.core.climate import models, sample_dataset
from riskbot.core.climate.assumptions import DEFAULT_ASSUMPTIONS, carbon_price, normalise_sector
from riskbot.core.climate.transition import (
    TransitionModel,
    discounted_price_sum,
    price_schedule,
    run_transition,
    simulate_portfolio_losses,
)

SPEC = catalog.Q3_TRANSITION


def _step(out, step_id):
    return next(s for s in out.traces[0].steps if s.id == step_id)


def three_issuers(as_of=dt.date(2020, 6, 30), with_short=True) -> ClimatePortfolio:
    """Hand-computable book. Revenue in currency units (2e6 = USD 2 m)."""
    hs = [
        ClimateHolding(issuer="A", sector="energy", market_value=100, evic=1000, revenue=2e6,
                       scope1=8, scope2=2, data_quality=1, emissions_year=2019),
        ClimateHolding(issuer="B", sector="Technology", market_value=300, evic=6000, revenue=5e6,
                       scope1=4, scope2=1, data_quality=1, emissions_year=2019),
        ClimateHolding(issuer="C", sector="utilities", market_value=100, evic=200, revenue=1e6,
                       scope1=20, scope2=10, data_quality=1, emissions_year=2019),
    ]
    if with_short:
        hs.append(ClimateHolding(issuer="S", sector="energy", market_value=-250, evic=100, revenue=1e6,
                                 scope1=900, scope2=100, data_quality=1))
    return ClimatePortfolio(name="three", as_of=as_of, synthetic=True, holdings=hs)


H1 = {"horizon_years": 1, "n_sims": 200}


# --------------------------------------------------------------------------- price paths


def test_price_paths_match_specification():
    assert [carbon_price("orderly", t) for t in (0, 1, 9, 10, 12)] == [60, 70, 150, 155, 165]
    assert [carbon_price("disorderly", t) for t in (0, 3, 6, 9)] == [35, 35, 250, 250]
    assert carbon_price("disorderly", 4) == pytest.approx(35 + 215 / 3)
    assert [carbon_price("hot_house", t) for t in (0, 5, 30)] == [35, 40, 65]
    out = run_transition(sample_dataset(), {"scenario": "orderly", "price_path": "high", "horizon_years": 9,
                                            "n_sims": 100}, 0)
    assert out.metrics["carbon_price_end"].value == pytest.approx(300.0)


def test_discounted_price_sum_closed_form_for_flat_price():
    # flat price p: A = p * (1 - (1+r)^-H) / r (ordinary annuity)
    a = DEFAULT_ASSUMPTIONS.with_(price_override=40.0)
    _, prices, disc = price_schedule("orderly", "central", 10, a)
    assert discounted_price_sum(prices, disc) == pytest.approx(40 * (1 - 1.05 ** -10) / 0.05)


# --------------------------------------------------------------------------- hand-computed example


def test_hand_computed_three_issuer_example():
    out = run_transition(three_issuers(), {**H1, "scenario": "orderly", "price_path": "central"}, 7)
    assert check_output(SPEC, out) == []
    # A = p_1 / 1.05 = 70 / 1.05 = 66.6667 USD per t/yr
    # A: PV = 10 * 0.7 * 66.667 = 466.67 -> 0.46667 * 100 = 46.667
    # B: PV = 5 * 0.2 * 66.667 = 66.667 -> /6000 = 0.011111 * 300 = 3.3333
    # C: PV = 30 * 0.5 * 66.667 = 1000 -> /200 = 5 -> capped at 1 -> 100
    # total 150 / long MV 500 = 0.30 (short S excluded)
    assert _step(out, "central_loss").value == pytest.approx(0.30)
    assert _step(out, "long_book").value == pytest.approx(500)
    # WACI: weights .2/.6/.2, intensities 10/2=5, 5/5=1, 30/1=30 -> 1 + .6 + 6 = 7.6
    assert out.metrics["waci"].value == pytest.approx(7.6)
    # FE: 100/1000*10 + 300/6000*5 + 100/200*30 = 1 + 0.25 + 15 = 16.25
    assert out.metrics["financed_emissions"].value == pytest.approx(16.25)
    assert out.metrics["estimated_share"].value == 0.0
    assert out.metrics["carbon_price_end"].value == pytest.approx(70.0)
    # pathway (as_of 2020 -> factor 1): .2*600 + .6*15 + .2*1500 = 429 -> 7.6 / 429
    assert out.metrics["alignment_ratio"].value == pytest.approx(7.6 / 429)
    # low sigma (data quality 1 -> 0.05) keeps the Monte Carlo median close to the central value
    assert out.metrics["loss_pct"].value == pytest.approx(0.30, rel=0.02)
    assert out.metrics["loss_amount"].value == pytest.approx(out.metrics["loss_pct"].value * 500)
    assert out.labels["exposure_level"] == "high"
    capped = [r for r in _step(out, "central_loss").table if r["capped"]]
    assert [r["issuer"] for r in capped] == ["C"] and capped[0]["shock"] == -1.0


def test_pathway_decline_factor():
    out = run_transition(three_issuers(as_of=dt.date(2022, 1, 31)), H1, 0)
    assert _step(out, "pathway_intensity").value == pytest.approx(429 * 0.93 ** 2)


def test_shorts_excluded():
    with_s = run_transition(three_issuers(with_short=True), H1, 3)
    without = run_transition(three_issuers(with_short=False), H1, 3)
    for k in with_s.metrics:
        assert with_s.metrics[k].value == pytest.approx(without.metrics[k].value), k
    assert any(f.check == "short_excluded" and f.subject == "S" for f in with_s.findings)
    assert _step(with_s, "long_book").table[0]["issuer"] == "S"


# --------------------------------------------------------------------------- properties


def test_zero_carbon_price_gives_zero_loss():
    out = run_transition(sample_dataset(), {}, 0, DEFAULT_ASSUMPTIONS.with_(price_override=0.0))
    for k in ("loss_pct", "loss_p05", "loss_p95", "loss_amount", "carbon_price_end"):
        assert out.metrics[k].value == 0.0
    assert out.labels["exposure_level"] == "low"


def test_full_pass_through_gives_zero_loss():
    a = DEFAULT_ASSUMPTIONS.with_(pass_through={s: 1.0 for s in DEFAULT_ASSUMPTIONS.pass_through})
    out = run_transition(sample_dataset(), {"scenario": "disorderly", "price_path": "high"}, 0, a)
    assert out.metrics["loss_p95"].value == 0.0 and out.metrics["loss_pct"].value == 0.0
    assert out.metrics["waci"].value > 0  # footprint unaffected


@pytest.mark.parametrize("scenario", ["orderly", "disorderly", "hot_house"])
def test_loss_monotone_in_price_path(scenario):
    vals = {}
    for path in ("low", "central", "high"):
        out = run_transition(sample_dataset(), {"scenario": scenario, "price_path": path, "n_sims": 500}, 11)
        vals[path] = out
    for k in ("loss_pct", "loss_p05", "loss_p95"):
        assert vals["low"].metrics[k].value <= vals["central"].metrics[k].value <= vals["high"].metrics[k].value


def test_cap_at_minus_100_percent():
    p = ClimatePortfolio(name="cap", as_of=dt.date(2026, 1, 1), synthetic=True, holdings=[
        ClimateHolding(issuer="X", sector="utilities", market_value=50, evic=10, revenue=1e6,
                       scope1=1e6, scope2=0, data_quality=1)])
    out = run_transition(p, {"price_path": "high", "n_sims": 300}, 0)
    for k in ("loss_pct", "loss_p05", "loss_p95"):
        assert out.metrics[k].value == pytest.approx(1.0)
    assert out.metrics["loss_amount"].value == pytest.approx(50)
    assert _step(out, "central_loss").table[0]["shock"] == -1.0
    assert any("cap" in w for w in out.warnings)


def test_sigma_zero_monte_carlo_equals_deterministic():
    rng = np.random.default_rng(0)
    c = np.array([0.1, 0.5, 2.0, 0.0])
    mv = np.array([10.0, 20.0, 30.0, 40.0])
    z = rng.standard_normal((1000, 4))
    sims = simulate_portfolio_losses(c, mv, np.zeros(4), z)
    assert np.allclose(sims, np.sum(mv * np.minimum(c, 1)))
    # mean-preserving lognormal: without the cap, E[L] -> sum MV c (law of large numbers)
    sims = simulate_portfolio_losses(np.array([0.01, 0.02]), np.array([1.0, 1.0]), np.array([0.3, 0.3]),
                                     np.random.default_rng(1).standard_normal((200_000, 2)))
    assert sims.mean() == pytest.approx(0.03, rel=0.01)


def test_quantiles_ordered_and_central_in_trace():
    for scen, path in itertools.product(["orderly", "hot_house"], ["low", "high"]):
        out = run_transition(sample_dataset(), {"scenario": scen, "price_path": path, "n_sims": 500}, 5)
        m = out.metrics
        assert m["loss_p05"].value <= m["loss_pct"].value <= m["loss_p95"].value
        stats = {r["statistic"]: r["value"] for r in _step(out, "loss_pct").table}
        assert stats["central"] == pytest.approx(_step(out, "central_loss").value)


def _emissions_by_issuer(out):
    return {r["issuer"]: (r["emissions_tco2e"], r["source"]) for r in _step(out, "central_loss").table}


def test_conservative_imputes_at_least_sector_average():
    ds = sample_dataset()
    avg = run_transition(ds, {"missing_data": "sector_average"}, 0)
    con = run_transition(ds, {"missing_data": "conservative"}, 0)
    ea, ec = _emissions_by_issuer(avg), _emissions_by_issuer(con)
    imputed = [k for k, (_, src) in ea.items() if src == "imputed"]
    assert len(imputed) >= 5
    for k in imputed:
        assert ec[k][0] >= ea[k][0] > 0
    assert con.metrics["financed_emissions"].value >= avg.metrics["financed_emissions"].value
    assert con.metrics["estimated_share"].value >= avg.metrics["estimated_share"].value > 0


def test_sector_average_imputation_hand_computed():
    hs = [ClimateHolding(issuer=f"P{i}", sector="materials", market_value=1, evic=1e9, revenue=1e6,
                         scope1=v, scope2=0, data_quality=2) for i, v in enumerate([100.0, 200.0, 400.0])]
    hs.append(ClimateHolding(issuer="M", sector="materials", market_value=1, evic=1e9, revenue=3e6))
    hs.append(ClimateHolding(issuer="N", sector="spaceflight", market_value=1, evic=1e9, revenue=2e6))
    p = ClimatePortfolio(name="imp", as_of=dt.date(2026, 1, 1), synthetic=True, holdings=hs)
    e_avg = _emissions_by_issuer(run_transition(p, {"n_sims": 100}, 0))
    e_con = _emissions_by_issuer(run_transition(p, {"missing_data": "conservative", "n_sims": 100}, 0))
    assert e_avg["M"] == (pytest.approx(3 * 200.0), "imputed")  # median of 100, 200, 400 t/USDm
    assert e_con["M"][0] == pytest.approx(3 * 300.0)  # linear-interpolated 75th percentile
    ref = DEFAULT_ASSUMPTIONS.sector_reference["other"]  # unknown sector, no peers -> fallback table
    assert e_avg["N"][0] == pytest.approx(2 * ref.median) and e_con["N"][0] == pytest.approx(2 * ref.p75)


def test_exclude_has_no_imputed_contribution():
    ds = sample_dataset()
    out = run_transition(ds, {"missing_data": "exclude"}, 0)
    assert out.metrics["estimated_share"].value == 0.0
    rows = _step(out, "central_loss").table
    excl = [r for r in rows if r["source"] == "excluded"]
    assert len(excl) == sum(1 for h in ds.holdings if h.market_value > 0 and (h.scope1 is None or h.scope2 is None))
    assert all(r["central_loss"] == 0 and r["emissions_tco2e"] is None for r in excl)
    assert "excluded for missing data: 6 holdings" in _step(out, "long_book").substitution
    # loss denominator stays the full long book
    assert _step(out, "long_book").value == pytest.approx(sum(h.market_value for h in ds.holdings
                                                               if h.market_value > 0))


def test_scope3_increases_footprint():
    base = run_transition(sample_dataset(), {}, 0)
    s3 = run_transition(sample_dataset(), {"include_scope3": True}, 0)
    assert s3.metrics["financed_emissions"].value > base.metrics["financed_emissions"].value
    assert s3.metrics["loss_pct"].value > base.metrics["loss_pct"].value


def test_exposure_level_thresholds():
    lv = {}
    for scen, path in [("hot_house", "low"), ("orderly", "low"), ("disorderly", "high")]:
        out = run_transition(sample_dataset(), {"scenario": scen, "price_path": path}, 0)
        x = out.metrics["loss_pct"].value
        expected = "low" if x < 0.02 else "moderate" if x < 0.08 else "high"
        assert out.labels["exposure_level"] == expected
        lv[(scen, path)] = expected
    assert set(lv.values()) == {"low", "moderate", "high"}  # sample is designed to span all three


# --------------------------------------------------------------------------- contract behaviour


def test_every_default_plan_variation_and_extra_conforms():
    plan = catalog.DEFAULT_PLANS[catalog.Q3]
    by_id = {m.spec.model_id: m for m in models()}
    ds = sample_dataset()
    dims = plan.grid.dimensions
    for combo in itertools.product(*dims.values()):
        params = {**plan.grid.fixed, **dict(zip(dims, combo))}
        out = by_id[plan.grid.model_id].run(ds, params, 123)
        assert check_output(by_id[plan.grid.model_id].spec, out) == [], combo
        assert out.params == {**params}
        tid = out.traces[0].trace_id
        assert tid.startswith("q3.transition-") and len(tid) == len("q3.transition-") + 12
        assert set(out.traces[0].result) == set(out.metrics)
    for extra in plan.extras:
        out = by_id[extra.model_id].run(ds, extra.params, 123)
        assert check_output(by_id[extra.model_id].spec, out) == []


def test_determinism_and_seed_dependence():
    ds = sample_dataset()
    a = TransitionModel().run(ds, {}, 99)
    b = TransitionModel().run(sample_dataset(), {}, 99)
    assert a.model_dump() == b.model_dump()
    c = TransitionModel().run(ds, {}, 100)
    assert c.traces[0].trace_id != a.traces[0].trace_id
    assert c.metrics["waci"].value == a.metrics["waci"].value  # footprint does not depend on the seed


def test_wrong_dataset_kind_and_bad_params():
    for m in models():
        with pytest.raises(ValidationFailed):
            m.run(fake_dataset(catalog.Q1), {}, 0)
        with pytest.raises(ValidationFailed):
            m.run({"kind": "balance_sheet"}, {}, 0)
    with pytest.raises(ValidationFailed):
        TransitionModel().run(sample_dataset(), {"scenario": "net_zero"}, 0)
    only_short = ClimatePortfolio(name="s", as_of=dt.date(2026, 1, 1), synthetic=True, holdings=[
        ClimateHolding(issuer="S", sector="energy", market_value=-1, evic=1, revenue=1)])
    with pytest.raises(ValidationFailed):
        TransitionModel().run(only_short, {}, 0)


def test_accepts_dict_dataset_and_fake_contract_dataset():
    ds = sample_dataset()
    a = TransitionModel().run(ds.model_dump(mode="json"), {"n_sims": 100}, 1)
    b = TransitionModel().run(ds, {"n_sims": 100}, 1)
    assert a.metrics["loss_pct"].value == b.metrics["loss_pct"].value
    out = TransitionModel().run(fake_dataset(catalog.Q3), {}, 0)
    assert check_output(SPEC, out) == []


def test_normalise_sector():
    assert normalise_sector(" Health Care ") == ("health_care", True)
    assert normalise_sector("Real-Estate") == ("real_estate", True)
    assert normalise_sector("crypto") == ("other", False)
    assert math.isclose(DEFAULT_ASSUMPTIONS.sigma(None, False), 0.5)
    assert DEFAULT_ASSUMPTIONS.sigma(1, True) == 0.6


def test_trace_contains_required_steps():
    out = run_transition(sample_dataset(), {}, 0)
    ids = [s.id for s in out.traces[0].steps]
    for sid in ("long_book", "carbon_price_end", "central_loss", "waci", "financed_emissions",
                "estimated_share", "pathway_intensity", "alignment_ratio", "loss_pct"):
        assert sid in ids
    assert len(_step(out, "carbon_price_end").table) == 11  # years t = 0..10
    row = _step(out, "central_loss").table[0]
    assert {"sector", "emissions_tco2e", "source", "sigma", "pass_through", "pv_cost", "shock",
            "central_loss"} <= set(row)
    assert any("ILLUSTRATIVE" in a for a in out.traces[0].assumptions)
