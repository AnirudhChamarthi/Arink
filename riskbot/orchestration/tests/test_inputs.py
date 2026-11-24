"""Synchronous validation (before a run exists), calc, validate and the read-side facade."""

from __future__ import annotations

import datetime as dt

import pytest

from riskbot.contract import catalog, fakes, ports
from riskbot.contract.errors import LimitExceeded, NotFound, RiskbotError, ValidationFailed
from riskbot.contract.types import (
    BsAsset,
    CalcRequest,
    ClimateHolding,
    DataQualityFinding,
    MarketDataset,
    MarketPosition,
    QuestionId,
    RunRequest,
    Severity,
)
from riskbot.orchestration.tests.helpers import RaisingModel, make_service, registry_with

LIM = catalog.LIMITS


def _too_many_positions() -> MarketDataset:
    pos = [MarketPosition(ticker=f"C{i}", asset_class="cash", quantity=1, price=1) for i in range(LIM["max_positions"] + 1)]
    return MarketDataset(name="big", as_of=dt.date(2026, 1, 1), synthetic=True, positions=pos, dates=[], returns={})


def _too_long_history() -> MarketDataset:
    n = LIM["max_history_days"] + 1
    dates = [dt.date(2000, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    return MarketDataset(name="long", as_of=dates[-1], synthetic=True, dates=dates, returns={"A": [0.0] * n},
                         positions=[MarketPosition(ticker="A", quantity=1, price=1)])


def _too_many_bs_items():
    ds = fakes.fake_dataset(QuestionId.Q2)
    extra = [BsAsset(id=f"a{i}", kind="other", book_value=1, market_value=1, coupon_rate=0, maturity_years=0,
                     repricing_years=0) for i in range(LIM["max_balance_sheet_items"])]
    return ds.model_copy(update={"assets": ds.assets + extra})


def _too_many_holdings():
    ds = fakes.fake_dataset(QuestionId.Q3)
    h = ClimateHolding(issuer="x", sector="energy", market_value=1, evic=1, revenue=1)
    return ds.model_copy(update={"holdings": [h] * (LIM["max_holdings"] + 1)})


LIMIT_CASES = [(QuestionId.Q1, _too_many_positions), (QuestionId.Q1, _too_long_history),
               (QuestionId.Q2, _too_many_bs_items), (QuestionId.Q3, _too_many_holdings)]


def test_service_satisfies_run_service_protocol(svc):
    for name in [n for n in dir(ports.RunService) if not n.startswith("_")]:
        assert callable(getattr(svc, name)), name


@pytest.mark.parametrize("q,make", LIMIT_CASES)
def test_limits_rejected_before_run_exists(svc, q, make):
    with pytest.raises(LimitExceeded):
        svc.start_run(RunRequest(question=q, dataset=make()), wait=True)
    assert svc.list_runs() == []


@pytest.mark.parametrize("q,make", LIMIT_CASES)
def test_limits_enforced_by_calc_and_validate(svc, q, make):
    ds = make()
    model_id = catalog.DEFAULT_PLANS[q].grid.model_id
    with pytest.raises(LimitExceeded):
        svc.calc(CalcRequest(model_id=model_id, dataset=ds))
    with pytest.raises(LimitExceeded):
        svc.validate(ds)


def test_dataset_kind_mismatch_rejected_before_run_exists(svc):
    with pytest.raises(ValidationFailed, match="market"):
        svc.start_run(RunRequest(question=QuestionId.Q1, dataset=fakes.fake_dataset(QuestionId.Q3)))
    assert svc.list_runs() == []


def test_plan_question_mismatch_rejected(svc):
    with pytest.raises(ValidationFailed, match="plan.question"):
        svc.start_run(RunRequest(question=QuestionId.Q1, dataset=fakes.fake_dataset(QuestionId.Q1),
                                 plan=catalog.DEFAULT_PLANS[QuestionId.Q2]))
    assert svc.list_runs() == []


def test_planner_errors_surface_synchronously():
    class StrictPlanner:
        def expand(self, plan, seed):
            raise ValidationFailed("unknown parameter 'foo'")

    svc = make_service(planner=StrictPlanner())
    with pytest.raises(ValidationFailed, match="foo"):
        svc.start_run(RunRequest(question=QuestionId.Q1, dataset=fakes.fake_dataset(QuestionId.Q1)))
    assert svc.list_runs() == []


def test_custom_plan_is_used(svc):
    plan = catalog.DEFAULT_PLANS[QuestionId.Q1].model_copy(deep=True)
    plan.grid.dimensions = {"method": ["normal", "historical"]}
    plan.extras = []
    rec = svc.start_run(RunRequest(question=QuestionId.Q1, dataset=fakes.fake_dataset(QuestionId.Q1), plan=plan),
                        wait=True)
    assert rec.n_variations == 2
    assert svc.get_result(rec.run_id).plan == plan


def test_calc_runs_model(svc):
    out = svc.calc(CalcRequest(model_id="q1.var", dataset=fakes.fake_dataset(QuestionId.Q1)))
    assert out.model_id == "q1.var" and "var" in out.metrics


def test_calc_errors(svc):
    with pytest.raises(NotFound):
        svc.calc(CalcRequest(model_id="q9.nope", dataset=fakes.fake_dataset(QuestionId.Q1)))
    with pytest.raises(ValidationFailed):
        svc.calc(CalcRequest(model_id="q1.var", dataset=fakes.fake_dataset(QuestionId.Q2)))
    with pytest.raises(ValidationFailed):  # contract error from the model propagates unchanged
        svc.calc(CalcRequest(model_id="q1.var", dataset=fakes.fake_dataset(QuestionId.Q1), params={"bad": 1}))


def test_calc_wraps_unexpected_exceptions():
    svc = make_service(registry=registry_with("q1.var"))
    with pytest.raises(RiskbotError) as info:
        svc.calc(CalcRequest(model_id="q1.var", dataset=fakes.fake_dataset(QuestionId.Q1)))
    assert type(info.value) is RiskbotError and "RuntimeError" in info.value.message


class _DqModel(fakes.FakeModel):
    def run(self, dataset, params, seed):
        out = super().run(dataset, params, seed)
        return out.model_copy(update={"findings": [DataQualityFinding(
            check="missing_returns", severity=Severity.WARNING, field="returns", subject="AAA", count=2,
            message="2 missing")]})


@pytest.mark.parametrize("q", list(QuestionId))
def test_validate_runs_the_questions_data_quality_model(q):
    models = [_DqModel(s) if s.model_id.endswith(".data_quality") and s.question == q else fakes.FakeModel(s)
              for s in catalog.MODEL_SPECS.values()]
    svc = make_service(registry=fakes.FakeRegistry(models))
    findings = svc.validate(fakes.fake_dataset(q))
    assert [f.check for f in findings] == ["missing_returns"]


def test_validate_reports_a_failing_data_quality_model():
    svc = make_service(registry=registry_with("q2.data_quality"))
    findings = svc.validate(fakes.fake_dataset(QuestionId.Q2))
    assert len(findings) == 1 and findings[0].severity == Severity.ERROR
    assert findings[0].check == "data_quality_model_failed" and "RuntimeError" in findings[0].message


def test_validate_without_data_quality_model():
    models = [fakes.FakeModel(s) for s in catalog.MODEL_SPECS.values() if s.model_id != "q3.data_quality"]
    svc = make_service(registry=fakes.FakeRegistry(models))
    assert svc.validate(fakes.fake_dataset(QuestionId.Q3))[0].check == "data_quality_model_missing"


def test_read_side_facade(svc):
    assert [q.question for q in svc.questions()] == list(catalog.QUESTIONS)
    assert len(svc.list_models()) == len(catalog.MODEL_SPECS)
    assert {s.model_id for s in svc.list_models(QuestionId.Q2)} == {
        "q2.resilience", "q2.reverse_stress", "q2.data_quality"}
    assert svc.sample_dataset(QuestionId.Q3).kind == "climate"
    with pytest.raises(NotFound):
        svc.get_trace("q1.var-000000000000")


def test_missing_sample_is_not_found():
    svc = make_service(samples={})
    with pytest.raises(NotFound):
        svc.sample_dataset(QuestionId.Q1)


def test_raising_model_helper_is_selective():
    m = RaisingModel(catalog.MODEL_SPECS["q1.var"], when=lambda p: p.get("method") == "evt")
    assert m.run(fakes.fake_dataset(QuestionId.Q1), {"method": "normal"}, 1).model_id == "q1.var"
