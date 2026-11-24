"""q2.resilience: hand-computed small bank, designed pass/fail, properties and conformance."""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist

import pytest

from riskbot.contract import catalog, conformance, fakes
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.types import LoanPool, QuestionId
from riskbot.core.balance_sheet import models, sample_dataset
from riskbot.core.balance_sheet.engine import Scenario, evaluate
from riskbot.core.balance_sheet.resilience import ResilienceModel

from .conftest import tiny_bank

MODEL = ResilienceModel()


def vasicek_stdlib(pd, rho, q):
    nd = NormalDist()
    return nd.cdf((nd.inv_cdf(pd) + math.sqrt(rho) * nd.inv_cdf(q)) / math.sqrt(1 - rho))


def zc_dv(mv, T, y, dy):
    d, c = T / (1 + y), T * (T + 1) / (1 + y) ** 2
    return mv * (-d * dy + 0.5 * c * dy * dy)


# ------------------------------------------------------------------------------------------------ hand check


def test_tiny_bank_against_hand_calculation(tiny):
    out = MODEL.run(tiny, {"rate_shock_bp": 100, "run_speed": "slow"}, seed=0)
    assert conformance.check_output(MODEL.spec, out) == []
    m = {k: v.value for k, v in out.metrics.items()}
    dy, y = 0.01, 0.04
    dv_hqla, dv_afs, dv_htm = zc_dv(200, 5, y, dy), zc_dv(100, 4, y, dy), zc_dv(250, 10, y, dy)
    # loans: one cash flow at the 0.5y repricing date, yield 6%
    d_l, c_l = 0.5 / 1.06, 0.5 * 1.5 / 1.06**2
    dv_loans = 500 * (-d_l * dy + 0.5 * c_l * dy * dy)
    d_a = dv_hqla + dv_afs + dv_htm + dv_loans
    d_liab = -800 * 2 * (1 - 0.5) * dy - 50 * (10 / 365) * dy
    d_swap_dur = (1.04 / 0.04) * (1 - 1.04**-3) / 1.04  # par bond closed form
    d_swaps = 40 * d_swap_dur * dy
    assert m["delta_eve"] == pytest.approx(d_a - d_liab + d_swaps, rel=1e-10)
    assert m["delta_eve_pct_cet1"] == pytest.approx(m["delta_eve"] / 60, rel=1e-12)
    # NII: cash 100 full year, loans 500 for half a year, deposits beta 0.5, wholesale after 10 days, swap
    nii = 100 * dy + 500 * dy * 0.5 - 800 * 0.5 * dy - 50 * dy * (1 - 10 / 365) + 40 * dy
    assert m["delta_nii_12m"] == pytest.approx(nii, rel=1e-10)
    credit = 500 * 0.4 * vasicek_stdlib(0.02, 0.15, 0.90)
    assert m["credit_loss"] == pytest.approx(credit, rel=1e-9)
    assert m["unrealised_securities_loss"] == pytest.approx(-(dv_hqla + dv_afs + dv_htm), rel=1e-10)
    assert m["deposit_outflow"] == pytest.approx(80.0)
    # need 130: cash 100, then 30 of HQLA at post-shock value -> no fire sale
    hq_post = 200 + dv_hqla
    share = 30 / hq_post
    assert m["fire_sale_loss"] == pytest.approx(share * 200 - 30, rel=1e-10)
    # without fire sales every HQLA/AFS shock loss lands in capital (realised or not); HTM at cost
    assert m["cet1_after"] == pytest.approx(60 - credit + dv_hqla + dv_afs, rel=1e-10)
    assert m["capital_ratio_before"] == pytest.approx(0.1)
    assert m["capital_ratio_after"] == pytest.approx(m["cet1_after"] / 600, rel=1e-12)
    assert m["lcr_before"] == pytest.approx(300 / (800 * 0.15 + 50))
    assert m["lcr_after"] == pytest.approx((hq_post - 30) / (720 * 0.15), rel=1e-10)
    # mark to market adds the whole HTM gap to post-shock value
    mtm = MODEL.run(tiny, {"rate_shock_bp": 100, "run_speed": "slow", "htm_treatment": "mark_to_market"}, 0)
    assert mtm.metrics["cet1_after"].value == pytest.approx(m["cet1_after"] - (300 - (250 + dv_htm)), rel=1e-10)


def test_tiny_bank_fire_sale_accounting(tiny):
    """Uniform 50% outflow at 0 bp: need 450 = cash 100 + HQLA 200 + 150 from AFS (100) then HTM."""
    res = evaluate(tiny, Scenario(rate_shock_bp=0, run_speed="uniform", uniform_outflow=0.5))
    lam, pool = 0.05, 350.0
    s = res.fire_sale.share
    assert s * pool * math.exp(-lam * s) == pytest.approx(150.0, rel=1e-10)
    sold_htm_mv = s * pool - 100
    carrying_sold = 100 + sold_htm_mv / 250 * 300
    assert res.fire_sale_carrying_sold == pytest.approx(carrying_sold, rel=1e-10)
    assert res.fire_sale_loss == pytest.approx(carrying_sold - 150.0, rel=1e-9)  # HQLA sold at value: no loss
    credit = 500 * 0.4 * vasicek_stdlib(0.02, 0.15, 0.90)
    assert res.cet1_after == pytest.approx(60 - credit - (carrying_sold - 150), rel=1e-9)
    assert res.hqla_after == pytest.approx(0.0, abs=1e-9)
    assert res.lcr_after == 0.0 and res.verdict == "fail"


def test_shortfall_recorded_when_everything_is_sold(tiny):
    res = evaluate(tiny, Scenario(rate_shock_bp=0, run_speed="uniform", uniform_outflow=0.9))
    assert res.fire_sale.method == "sell_all"
    assert res.liquidity_shortfall == pytest.approx(770 - 300 - 350 * math.exp(-0.05), rel=1e-10)
    assert res.liquidity_breach and res.lcr_after == 0.0
    assert any("shortfall" in w for w in res.warnings)


def test_zero_shock_no_run_only_credit_loss(tiny):
    res = evaluate(tiny, Scenario(rate_shock_bp=0, run_speed="none"))
    assert res.delta_eve == 0 and res.delta_nii_12m == 0 and res.fire_sale_loss == 0
    assert res.cet1_after == pytest.approx(60 - res.credit_loss)
    assert res.lcr_after == pytest.approx(res.lcr_before)


def test_credit_loss_linear_in_ead(tiny):
    base = evaluate(tiny, Scenario()).credit_loss
    for k in (0.5, 2.0, 3.7):
        pools = [LoanPool(segment="all", ead=500 * k, pd=0.02, lgd=0.4, asset_correlation=0.15)]
        bank = tiny_bank(loan_pools=pools)
        assert evaluate(bank, Scenario()).credit_loss == pytest.approx(k * base, rel=1e-12)


def test_adverse_credit_loss_exceeds_base(bank):
    assert evaluate(bank, Scenario(loss_severity="adverse")).credit_loss > evaluate(bank, Scenario()).credit_loss


def test_given_duration_is_used(tiny):
    assets = [a.model_copy(update={"modified_duration": 2.0, "convexity": 0.0}) if a.id == "afs" else a
              for a in tiny.assets]
    res = evaluate(tiny_bank(assets=assets), Scenario(rate_shock_bp=100))
    row = next(r for r in res.assets if r.id == "afs")
    assert row.dv == pytest.approx(-100 * 2.0 * 0.01) and row.source == "given"


# ------------------------------------------------------------------------------------------------ sample design


def test_designed_base_case_passes(bank):
    out = MODEL.run(bank, {"rate_shock_bp": 100, "run_speed": "slow", "loss_severity": "base",
                           "htm_treatment": "at_cost"}, 0)
    assert out.labels == {"verdict": "pass", "binding_constraint": "none"}


def test_designed_severe_case_fails(bank):
    out = MODEL.run(bank, {"rate_shock_bp": 300, "run_speed": "fast", "loss_severity": "adverse",
                           "htm_treatment": "mark_to_market"}, 0)
    assert out.labels["verdict"] == "fail"
    assert out.metrics["capital_ratio_after"].value < 0.07 and out.metrics["lcr_after"].value < 1.0


def test_sample_shape(bank):
    a_book = sum(a.book_value for a in bank.assets)
    sec = sum(a.book_value for a in bank.assets if a.kind.endswith("securities"))
    htm = sum(a.book_value for a in bank.assets if a.kind == "htm_securities")
    dep = sum(d.balance for d in bank.deposits)
    assert bank.synthetic and 9e9 < a_book < 11e9
    assert 0.2 < sec / a_book < 0.3 and 0.4 < htm / sec < 0.6
    assert 0.65 < dep / a_book < 0.75 and len(bank.loan_pools) == 4 and bank.hedges
    assert {"cro_vacancy_months", "hedges_reduced_last_year", "deposit_growth_2y"} <= set(bank.governance)


@pytest.mark.parametrize("run", ["none", "slow", "fast"])
@pytest.mark.parametrize("htm", ["at_cost", "mark_to_market"])
def test_capital_falls_monotonically_with_shock(bank, run, htm):
    shocks = list(range(-200, 601, 25))
    caps = [evaluate(bank, Scenario(rate_shock_bp=s, run_speed=run, htm_treatment=htm)).capital_ratio_after
            for s in shocks]
    assert all(b <= a + 1e-12 for a, b in zip(caps, caps[1:]))
    assert caps[-1] < caps[0]


def test_sample_has_positive_duration_gap(bank):
    out = next(m for m in models() if m.spec.model_id == "q2.data_quality").run(bank, {}, 0)
    assert out.metrics["duration_gap_years"].value > 0
    assert evaluate(bank, Scenario(rate_shock_bp=100)).delta_eve < 0


@pytest.mark.parametrize("shock", [0, 100, 200, 300, 600])
@pytest.mark.parametrize("run", ["none", "slow", "fast"])
def test_mark_to_market_never_above_at_cost(bank, shock, run):
    at_cost = evaluate(bank, Scenario(rate_shock_bp=shock, run_speed=run)).cet1_after
    mtm = evaluate(bank, Scenario(rate_shock_bp=shock, run_speed=run, htm_treatment="mark_to_market")).cet1_after
    assert mtm <= at_cost + 1e-9


def test_faster_run_never_improves_liquidity(bank):
    for s in (-200, 100, 300):
        lcrs = [evaluate(bank, Scenario(rate_shock_bp=s, run_speed=r)).lcr_after for r in ("none", "slow", "fast")]
        assert lcrs[0] >= lcrs[1] >= lcrs[2]


# ------------------------------------------------------------------------------------------------ contract


def _default_plan_calls():
    plan = catalog.DEFAULT_PLANS[QuestionId.Q2]
    dims = plan.grid.dimensions
    calls = [(plan.grid.model_id, {**plan.grid.fixed, **dict(zip(dims, combo))})
             for combo in itertools.product(*dims.values())]
    return calls + [(e.model_id, dict(e.params)) for e in plan.extras]


def test_every_default_plan_variation_conforms(bank):
    by_id = {m.spec.model_id: m for m in models()}
    calls = _default_plan_calls()
    assert len(calls) == 35
    for model_id, params in calls:
        model = by_id[model_id]
        out = model.run(bank, params, seed=123)
        assert conformance.check_output(model.spec, out) == [], (model_id, params)
        assert out.params == conformance.resolve_params(model.spec, params)
        steps = {s.id: s for t in out.traces for s in t.steps}
        for key, metric in out.metrics.items():
            assert steps[metric.trace_step].value == pytest.approx(metric.value, rel=1e-12)
            assert out.traces[0].result[key] == metric.value
        assert out.traces[0].trace_id.startswith(model_id + "-")


def test_models_export_matches_catalog():
    ms = models()
    assert [m.spec for m in ms] == [catalog.Q2_RESILIENCE, catalog.Q2_REVERSE_STRESS, catalog.Q2_DATA_QUALITY]
    from riskbot.contract.ports import Model
    assert all(isinstance(m, Model) for m in ms)


def test_extreme_parameters_conform(bank, tiny):
    for ds in (bank, tiny):
        for p in ({"rate_shock_bp": -400, "run_speed": "fast", "fire_sale_impact": 1.0},
                  {"rate_shock_bp": 600, "run_speed": "fast", "fire_sale_impact": 0.0, "lcr_threshold": 0.0},
                  {"rate_shock_bp": 0, "run_speed": "none", "capital_threshold": 0.3}):
            assert conformance.check_output(MODEL.spec, MODEL.run(ds, p, 0)) == []


def test_minimal_bank_without_funding_conforms(tiny):
    bank = tiny_bank(deposits=[], wholesale_funding=[], hedges=[])
    out = MODEL.run(bank, {}, 0)
    assert conformance.check_output(MODEL.spec, out) == []
    assert out.metrics["lcr_before"].value == 100.0  # capped: no stressed outflows


def test_determinism(bank):
    a = MODEL.run(bank, {"run_speed": "fast"}, 5)
    b = MODEL.run(sample_dataset(), {"run_speed": "fast"}, 5)
    assert a.model_dump() == b.model_dump()
    c = MODEL.run(bank, {"run_speed": "fast"}, 6)
    assert c.traces[0].trace_id != a.traces[0].trace_id
    assert {k: v.value for k, v in c.metrics.items()} == {k: v.value for k, v in a.metrics.items()}
    assert sample_dataset(0) == sample_dataset(0) and sample_dataset(1) != sample_dataset(0)


# ------------------------------------------------------------------------------------------------ errors


@pytest.mark.parametrize("model", models(), ids=lambda m: m.spec.model_id)
@pytest.mark.parametrize("q", [QuestionId.Q1, QuestionId.Q3])
def test_wrong_dataset_kind_raises(model, q):
    with pytest.raises(ValidationFailed):
        model.run(fakes.fake_dataset(q), {}, 0)


@pytest.mark.parametrize("model", models(), ids=lambda m: m.spec.model_id)
def test_dict_inputs(model, bank):
    with pytest.raises(ValidationFailed):
        model.run({"kind": "market"}, {}, 0)
    with pytest.raises(ValidationFailed):
        model.run({"kind": "balance_sheet", "name": "x"}, {}, 0)
    assert conformance.check_output(model.spec, model.run(bank.model_dump(mode="json"), {}, 0)) == []


def test_bad_params_raise(bank):
    with pytest.raises(ValidationFailed):
        MODEL.run(bank, {"rate_shock_bp": 900}, 0)
    with pytest.raises(ValidationFailed):
        MODEL.run(bank, {"nonsense": 1}, 0)


def test_inconsistent_data_raises(tiny):
    unreconciled = tiny_bank(loan_pools=[LoanPool(segment="all", ead=100, pd=0.02, lgd=0.4, asset_correlation=0.1)])
    with pytest.raises(ValidationFailed, match="reconcile"):
        MODEL.run(unreconciled, {}, 0)
    dupes = tiny_bank(assets=tiny.assets + [tiny.assets[0]])
    with pytest.raises(ValidationFailed, match="duplicate"):
        MODEL.run(dupes, {}, 0)
    inf_bank = tiny.model_copy(update={"policy_rate": float("inf")})
    with pytest.raises(ValidationFailed):
        MODEL.run(inf_bank, {}, 0)
