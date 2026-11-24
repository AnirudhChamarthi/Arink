"""Executor tests: success, error capture, contract-violation capture, ordered parallel execution."""

import threading

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.fakes import FakeModel, fake_dataset
from riskbot.contract.types import QuestionId

Q1, Q2 = QuestionId.Q1, QuestionId.Q2


class ExplodingModel:
    spec = catalog.MODEL_SPECS["q1.var"]

    def run(self, dataset, params, seed):
        raise ZeroDivisionError("division by zero in tail fit")


class BrokenModel(FakeModel):
    """Returns an output that breaks the contract: wrong metric value vs trace, undeclared metric."""

    def run(self, dataset, params, seed):
        out = super().run(dataset, params, seed)
        metrics = dict(out.metrics)
        metrics["var"] = metrics["var"].model_copy(update={"value": metrics["var"].value + 1.0})
        return out.model_copy(update={"metrics": metrics})


class MissingMetricModel(FakeModel):
    def run(self, dataset, params, seed):
        out = super().run(dataset, params, seed)
        return out.model_copy(update={"metrics": {k: v for k, v in out.metrics.items() if k != "es"}})


def _specs(q=Q1):
    return services.planner().expand(catalog.DEFAULT_PLANS[q], 3)


def test_success(fake_registry):
    spec = _specs()[0]
    r = services.executor(fake_registry).execute(spec, fake_dataset(Q1))
    assert r.error is None and r.output is not None
    assert r.output.params == spec.params
    assert r.duration_ms >= 0


def test_exception_captured():
    reg = services.registry()
    reg.register(ExplodingModel())
    r = services.executor(reg).execute(_specs()[0], fake_dataset(Q1))
    assert r.output is None
    assert r.error == "ZeroDivisionError: division by zero in tail fit"


def test_wrong_dataset_and_unknown_model_captured(fake_registry):
    ex = services.executor(fake_registry)
    r = ex.execute(_specs()[0], fake_dataset(Q2))
    assert r.error.startswith(ValidationFailed.__name__ + ":")
    r = services.executor(services.registry()).execute(_specs()[0], fake_dataset(Q1))
    assert r.error.startswith("NotFound:")


def test_contract_violation_captured():
    reg = services.registry()
    reg.register(BrokenModel(catalog.MODEL_SPECS["q1.var"]))
    r = services.executor(reg).execute(_specs()[0], fake_dataset(Q1))
    assert r.output is None
    assert r.error.startswith("ContractViolation: ")
    assert "differs from its trace step value" in r.error


def test_missing_metric_violation():
    reg = services.registry()
    reg.register(MissingMetricModel(catalog.MODEL_SPECS["q1.var"]))
    r = services.executor(reg).execute(_specs()[0], fake_dataset(Q1))
    assert r.output is None and "missing metric 'es'" in r.error


def test_execute_many_preserves_order_and_uses_threads(fake_registry):
    seen = set()

    class Spy(FakeModel):
        def run(self, dataset, params, seed):
            seen.add(threading.get_ident())
            return super().run(dataset, params, seed)

    reg = services.registry()
    for s in catalog.MODEL_SPECS.values():
        reg.register(Spy(s))
    specs = _specs(Q2)
    ex = services.executor(reg)
    par = ex.execute_many(specs, fake_dataset(Q2), max_workers=4)
    seq = ex.execute_many(specs, fake_dataset(Q2), max_workers=1)
    assert [r.spec for r in par] == specs
    assert [r.output for r in par] == [r.output for r in seq]
    assert all(r.error is None for r in par)
