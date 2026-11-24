"""Shared fixtures: a fresh ``FakeRunService`` and a TestClient over ``create_app`` for every test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from riskbot.api import create_app
from riskbot.contract.fakes import FakeRunService


@pytest.fixture
def service() -> FakeRunService:
    return FakeRunService()


@pytest.fixture
def client(service: FakeRunService) -> TestClient:
    # raise_server_exceptions=False so 500 responses are observed as a browser would see them.
    with TestClient(create_app(service), raise_server_exceptions=False) as c:
        yield c
