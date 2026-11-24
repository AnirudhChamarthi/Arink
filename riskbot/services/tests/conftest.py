import pytest

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.fakes import FakeModel


@pytest.fixture
def fake_registry():
    reg = services.registry()
    for spec in catalog.MODEL_SPECS.values():
        reg.register(FakeModel(spec))
    return reg
