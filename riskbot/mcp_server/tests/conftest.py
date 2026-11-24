"""Fixtures: a spy fake service and a server built on it."""

from __future__ import annotations

import pytest

from riskbot.mcp_server import create_server
from riskbot.mcp_server.tests.helpers import SpyRunService


@pytest.fixture
def service() -> SpyRunService:
    return SpyRunService()


@pytest.fixture
def server(service):
    return create_server(service)
