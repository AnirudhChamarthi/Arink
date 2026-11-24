"""The contract is internally consistent, and its fakes satisfy its own rules."""

import datetime as dt
import json

import pytest

from riskbot.contract import catalog, rules
from riskbot.contract.conformance import check_output, resolve_params
from riskbot.contract.errors import Conflict, NotFound, ValidationFailed
from riskbot.contract.fakes import FakeModel, FakeRunService, fake_dataset
from riskbot.contract.hashing import derive_seed, model_input_hash, variation_id
from riskbot.contract.types import (
    ControlStrength,
    FactorEdit,
    QuestionId,
    Rating,
    ReviewDecision,
    ReviewSubmission,
    RunRequest,
    RunResult,
    RunStatus,
)


def test_catalog_is_consistent():
    for spec in catalog.MODEL_SPECS.values():
        names = [p.name for p in spec.params]
        assert len(names) == len(set(names)), spec.model_id
        assert spec.model_id.split(".")[0] == {"q1_market": "q1", "q2_balance_sheet": "q2", "q3_transition": "q3"}[
            spec.question.value]
        for p in spec.params:
            if p.applies_when:
                assert set(p.applies_when) <= set(names)
            resolve_params(spec, {})  # defaults are valid
        if spec.method_param:
            assert spec.method_param in names
        if spec.pass_label:
            assert {"pass", "fail"} <= set(spec.labels[spec.pass_label])


@pytest.mark.parametrize("q", list(QuestionId))
def test_default_plans_reference_valid_models_params_and_values(q):
    plan = catalog.DEFAULT_PLANS[q]
    spec = catalog.MODEL_SPECS[plan.grid.model_id]
    assert spec.question == q
    for name, values in plan.grid.dimensions.items():
        for v in values:
            resolve_params(spec, {**plan.grid.fixed, name: v})
    for extra in plan.extras:
        resolve_params(catalog.MODEL_SPECS[extra.model_id], extra.params)


def test_resolve_params_defaults_validation_and_applies_when():
    spec = catalog.Q1_VAR
    eff = resolve_params(spec, {"method": "historical"})
    assert eff["confidence"] == 0.99 and "covariance" not in eff and "t_dof" not in eff
    assert "covariance" in resolve_params(spec, {"method": "normal"})
    t = resolve_params(spec, {"method": "student_t", "t_dof": 5})  # int accepted for float, converted
    assert t["t_dof"] == 5.0 and isinstance(t["t_dof"], float)
    for bad in ({"confidence": 1},):  # above the 0.999 maximum
        with pytest.raises(ValidationFailed):
            resolve_params(spec, bad)
    for bad in ({"method": "magic"}, {"confidence": 1.5}, {"window_days": 300}, {"nope": 1}, {"backtest": "yes"},
                {"horizon_days": True}):
        with pytest.raises(ValidationFailed):
            resolve_params(spec, bad)


@pytest.mark.parametrize("model_id", list(catalog.MODEL_SPECS))
def test_fake_models_conform(model_id):
    spec = catalog.MODEL_SPECS[model_id]
    ds = fake_dataset(spec.question)
    out = FakeModel(spec).run(ds, {}, 1)
    assert check_output(spec, out) == []
    assert out == FakeModel(spec).run(ds, {}, 1)  # deterministic


def test_check_output_catches_violations():
    spec = catalog.Q1_VAR
    out = FakeModel(spec).run(fake_dataset(QuestionId.Q1), {}, 1)
    broken = out.model_copy(update={"metrics": {**out.metrics, "var": out.metrics["var"].model_copy(
        update={"value": 99.0})}, "labels": {**out.labels, "basel_zone": "purple"}})
    problems = check_output(spec, broken)
    assert any("differs from its trace step" in p for p in problems)
    assert any("basel_zone" in p for p in problems)


def test_hashing_is_deterministic_and_order_independent():
    ds = fake_dataset(QuestionId.Q1)
    assert model_input_hash("q1.var", ds, {"a": 1, "b": 2}, 7) == model_input_hash("q1.var", ds, {"b": 2, "a": 1}, 7)
    assert variation_id("m", {"a": 1}) != variation_id("m", {"a": 2})
    assert 0 <= derive_seed(1, "v123") < 2**32


def test_rating_rules():
    assert rules.inherent_rating(1, 4) == Rating.LOW
    assert rules.inherent_rating(3, 3) == Rating.MEDIUM
    assert rules.inherent_rating(3, 5) == Rating.HIGH
    assert rules.inherent_rating(4, 4) == Rating.CRITICAL
    assert rules.residual_rating(Rating.CRITICAL, ControlStrength.STRONG) == Rating.MEDIUM
    assert rules.residual_rating(Rating.LOW, ControlStrength.STRONG) == Rating.LOW
    assert rules.overall_rating([Rating.LOW, Rating.HIGH]) == Rating.HIGH
    assert rules.backtest_verdict(0.2, 0.01) == "fail"


@pytest.mark.parametrize("q", list(QuestionId))
def test_fake_run_service_full_flow(q):
    svc = FakeRunService()
    rec = svc.start_run(RunRequest(question=q, dataset=svc.sample_dataset(q)), wait=True)
    assert rec.status == RunStatus.AWAITING_REVIEW
    res = svc.get_result(rec.run_id)
    assert RunResult.model_validate_json(res.model_dump_json()) == res  # JSON round trip
    tid = next(t.trace_id for v in res.variations if v.output for t in v.output.traces)
    assert svc.get_trace(tid).trace_id == tid
    fid = res.assessment.factors[0].factor_id
    rec2 = svc.submit_review(rec.run_id, ReviewSubmission(
        decision=ReviewDecision.APPROVE, reviewer="analyst",
        factor_edits=[FactorEdit(factor_id=fid, likelihood=5, impact=5, reason="test")]))
    assert rec2.status == RunStatus.APPROVED
    rep = svc.get_report(rec.run_id)
    assert rep.signoff and rep.signoff.reviewer == "analyst"
    assert rep.assessment.overrides and rep.assessment.factors[0].inherent == Rating.CRITICAL
    with pytest.raises(Conflict):
        svc.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.REJECT, reviewer="x"))
    with pytest.raises(NotFound):
        svc.get_run("missing")


def test_dataset_validation():
    ds = fake_dataset(QuestionId.Q1)
    raw = json.loads(ds.model_dump_json())
    raw["returns"]["AAA"] = raw["returns"]["AAA"][:-1]
    with pytest.raises(Exception):
        type(ds).model_validate(raw)
    raw = json.loads(ds.model_dump_json())
    raw["dates"][1] = raw["dates"][0]
    with pytest.raises(Exception):
        type(ds).model_validate(raw)


def test_dataset_union_discriminates_on_kind():
    from pydantic import TypeAdapter

    from riskbot.contract.types import Dataset

    ta = TypeAdapter(Dataset)
    for q in QuestionId:
        ds = fake_dataset(q)
        assert type(ta.validate_json(ds.model_dump_json())) is type(ds)


def test_fixed_now_is_timezone_aware():
    from riskbot.contract.fakes import FIXED_NOW

    assert FIXED_NOW.tzinfo is not None and FIXED_NOW.tzinfo.utcoffset(FIXED_NOW) == dt.timedelta(0)
