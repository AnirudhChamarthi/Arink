"""Registry and planner tests."""

import itertools

import pytest

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.errors import LimitExceeded, NotFound, ValidationFailed
from riskbot.contract.fakes import FakeModel
from riskbot.contract.hashing import derive_seed, variation_id
from riskbot.contract.types import ExtraRun, GridSpec, QuestionId, QuestionPlan

Q1, Q2, Q3 = QuestionId.Q1, QuestionId.Q2, QuestionId.Q3


# -- registry ---------------------------------------------------------------------------------

def test_registry_starts_empty_and_registers():
    reg = services.registry()
    assert reg.specs() == []
    m = FakeModel(catalog.MODEL_SPECS["q1.var"])
    reg.register(m)
    assert reg.get("q1.var") is m


def test_registry_duplicate_and_unknown():
    reg = services.registry()
    reg.register(FakeModel(catalog.MODEL_SPECS["q1.var"]))
    with pytest.raises(ValidationFailed):
        reg.register(FakeModel(catalog.MODEL_SPECS["q1.var"]))
    with pytest.raises(NotFound):
        reg.get("q9.nothing")
    with pytest.raises(ValidationFailed):
        reg.register(object())


def test_registry_specs_filter(fake_registry):
    assert [s.model_id for s in fake_registry.specs(Q2)] == ["q2.resilience", "q2.reverse_stress", "q2.data_quality"]
    assert len(fake_registry.specs()) == len(catalog.MODEL_SPECS)
    assert all(s.question == Q3 for s in fake_registry.specs(Q3))


# -- planner ----------------------------------------------------------------------------------

@pytest.mark.parametrize("q,n_grid,n_extra", [(Q1, 18, 1), (Q2, 32, 3), (Q3, 27, 1)])
def test_default_plans_counts(q, n_grid, n_extra):
    specs = services.planner().expand(catalog.DEFAULT_PLANS[q], 7)
    assert sum(s.role == "grid" for s in specs) == n_grid
    assert sum(s.role == "extra" for s in specs) == n_extra
    assert [s.role for s in specs] == ["grid"] * n_grid + ["extra"] * n_extra
    assert len({s.variation_id for s in specs}) == len(specs)
    assert all(s.question == q for s in specs)


def test_q1_applies_when_dedupe():
    specs = services.planner().expand(catalog.DEFAULT_PLANS[Q1], 7)
    grid = [s for s in specs if s.role == "grid"]
    for s in grid:
        assert ("covariance" in s.params) == (s.params["method"] in ("normal", "student_t", "montecarlo"))
        assert ("t_dof" in s.params) == (s.params["method"] == "student_t")
        assert ("n_sims" in s.params) == (s.params["method"] == "montecarlo")
    hist = [s for s in grid if s.params["method"] == "historical"]
    assert [s.params["window_days"] for s in hist] == [250, 750]


def test_params_are_effective_and_ids_and_seeds():
    plan = catalog.DEFAULT_PLANS[Q2]
    specs = services.planner().expand(plan, 123)
    for s in specs:
        assert s.variation_id == variation_id(s.model_id, s.params)
        assert s.seed == derive_seed(123, s.variation_id)
    first = specs[0]
    assert first.params["capital_threshold"] == 0.07  # defaults filled
    assert specs[-3].params["target"] == "capital" and specs[-2].params["target"] == "liquidity"


def test_deterministic_order_and_seed_dependence():
    plan = catalog.DEFAULT_PLANS[Q3]
    a = services.planner().expand(plan, 1)
    b = services.planner().expand(plan, 1)
    c = services.planner().expand(plan, 2)
    assert a == b
    assert [s.variation_id for s in a] == [s.variation_id for s in c]
    assert [s.seed for s in a] != [s.seed for s in c]
    # last dimension varies fastest (itertools.product order)
    expected = [dict(zip(["scenario", "price_path", "missing_data"], combo)) for combo in itertools.product(
        *catalog.DEFAULT_PLANS[Q3].grid.dimensions.values())]
    got = [{k: s.params[k] for k in ("scenario", "price_path", "missing_data")} for s in a if s.role == "grid"]
    assert got == expected


def test_duplicate_extras_collapse():
    plan = QuestionPlan(question=Q1, grid=GridSpec(model_id="q1.var", dimensions={"method": ["normal"]}),
                        extras=[ExtraRun(model_id="q1.data_quality"),
                                ExtraRun(model_id="q1.data_quality", params={"stale_days": 5})])
    specs = services.planner().expand(plan, 0)
    assert [s.role for s in specs] == ["grid", "extra"]


def _plan(**kw):
    base = dict(question=Q1, grid=GridSpec(model_id="q1.var", dimensions={"method": ["normal", "historical"]}))
    base.update(kw)
    return QuestionPlan(**base)


@pytest.mark.parametrize("plan", [
    _plan(grid=GridSpec(model_id="q9.unknown", dimensions={})),
    _plan(extras=[ExtraRun(model_id="q9.unknown")]),
    _plan(grid=GridSpec(model_id="q1.var", dimensions={"method": ["magic"]})),
    _plan(grid=GridSpec(model_id="q1.var", dimensions={"confidence": [1.5]})),
    _plan(grid=GridSpec(model_id="q1.var", dimensions={"no_such_param": [1]})),
    _plan(grid=GridSpec(model_id="q1.var", dimensions={"method": []})),
    _plan(grid=GridSpec(model_id="q1.var", dimensions={}, fixed={"horizon_days": "five"})),
    _plan(extras=[ExtraRun(model_id="q1.data_quality", params={"stale_days": 99})]),
    _plan(grid=GridSpec(model_id="q2.resilience", dimensions={})),  # wrong question
])
def test_invalid_plans(plan):
    with pytest.raises(ValidationFailed):
        services.planner().expand(plan, 0)


def test_limit_uses_distinct_variations():
    # 6 methods x 2 covariances = 12 raw but only 9 distinct (covariance collapses for 3 methods)
    grid = GridSpec(model_id="q1.var", dimensions={"method": catalog.Q1_METHODS, "covariance": ["sample", "ledoit_wolf"]})
    assert len(services.planner().expand(QuestionPlan(question=Q1, grid=grid, max_variations=9), 0)) == 9
    with pytest.raises(LimitExceeded):
        services.planner().expand(QuestionPlan(question=Q1, grid=grid, max_variations=8), 0)


def test_limit_global_cap():
    grid = GridSpec(model_id="q1.var", dimensions={"horizon_days": list(range(1, 21)),
                                                   "confidence": [0.9 + i * 0.001 for i in range(60)]})
    with pytest.raises(LimitExceeded):
        services.planner().expand(QuestionPlan(question=Q1, grid=grid, max_variations=1000), 0)


def test_extras_do_not_count_towards_grid_limit():
    plan = QuestionPlan(question=Q2, grid=GridSpec(model_id="q2.resilience", dimensions={"run_speed": ["slow"]}),
                        extras=catalog.DEFAULT_PLANS[Q2].extras, max_variations=1)
    assert len(services.planner().expand(plan, 0)) == 4


def test_empty_dimensions_gives_single_default_variation():
    plan = QuestionPlan(question=Q3, grid=GridSpec(model_id="q3.transition", dimensions={}))
    specs = services.planner().expand(plan, 0)
    assert len(specs) == 1 and specs[0].params["scenario"] == "orderly"


def test_satisfies_protocol():
    from riskbot.contract.ports import VariationPlanner
    p: VariationPlanner = services.planner()
    assert callable(p.expand)
