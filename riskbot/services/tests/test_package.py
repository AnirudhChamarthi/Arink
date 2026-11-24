"""Package entry points match CONTRACT.md section 2 and the Protocols of ports.py."""

import inspect

import pytest

import riskbot.services as services
from riskbot.contract import ports
from riskbot.contract.fakes import FakeRegistry

FACTORIES = [
    (lambda: services.registry(), ports.ModelRegistry),
    (lambda: services.planner(), ports.VariationPlanner),
    (lambda: services.executor(FakeRegistry()), ports.VariationExecutor),
    (lambda: services.comparator(), ports.Comparator),
    (lambda: services.verifier(), ports.NumberVerifier),
    (lambda: services.sqlite_store(":memory:"), ports.RunStore),
    (lambda: services.reporter(), ports.Reporter),
]


@pytest.mark.parametrize("factory,proto", FACTORIES, ids=lambda x: getattr(x, "__name__", ""))
def test_factory_implements_protocol(factory, proto):
    obj = factory()
    members = [n for n, v in vars(proto).items() if callable(v) and not n.startswith("_")]
    assert members
    for name in members:
        impl = getattr(obj, name)
        want = [p for p in inspect.signature(getattr(proto, name)).parameters if p != "self"]
        got = list(inspect.signature(impl).parameters)
        assert got == want, (proto.__name__, name, got, want)


def test_exports():
    for name in ["registry", "planner", "executor", "comparator", "verifier", "sqlite_store", "reporter"]:
        assert callable(getattr(services, name))
    assert list(inspect.signature(services.sqlite_store).parameters) == ["path"]
    assert list(inspect.signature(services.executor).parameters) == ["registry"]


def test_execute_many_available():
    assert callable(services.executor(FakeRegistry()).execute_many)
