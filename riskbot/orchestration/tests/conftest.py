"""Fixtures for the orchestration tests."""

from __future__ import annotations

import pytest

from riskbot.orchestration.tests.helpers import CREATED, make_service


@pytest.fixture(autouse=True)
def _close_services():
    """Close every service's checkpoint connection after each test (after background runs settle)."""
    yield
    while CREATED:
        svc = CREATED.pop()
        for t in list(svc._threads.values()):
            t.join(10)
        svc.close()


@pytest.fixture
def svc():
    return make_service()
