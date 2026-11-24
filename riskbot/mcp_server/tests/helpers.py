"""Shared helpers for the MCP server tests (imported as ``riskbot.mcp_server.tests.helpers``).

No async pytest plugin is installed, so tests drive the in-process ``mcp.Client`` with ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import Client

from riskbot.contract.fakes import FakeRunService


class SpyRunService(FakeRunService):
    """FakeRunService that records every service call (name, kwargs) for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def validate(self, dataset):
        self.calls.append(("validate", {}))
        return super().validate(dataset)

    def calc(self, request):
        self.calls.append(("calc", {"request": request}))
        return super().calc(request)

    def start_run(self, request, *, wait=False):
        self.calls.append(("start_run", {"request": request, "wait": wait}))
        return super().start_run(request, wait=wait)


def run_with_client(server, body: Callable[[Client], Awaitable[Any]]) -> Any:
    """Open an in-process client on ``server`` and run ``body(client)`` to completion."""

    async def main() -> Any:
        async with Client(server) as client:
            return await body(client)

    return asyncio.run(main())


def call(server, name: str, arguments: dict[str, Any] | None = None):
    """Call one tool in a fresh in-process session and return the ``CallToolResult``."""
    return run_with_client(server, lambda c: c.call_tool(name, arguments or {}))


def error_text(result) -> str:
    """Text of a tool-error result."""
    assert result.is_error, f"expected a tool error, got {result.structured_content!r}"
    return "".join(getattr(block, "text", "") for block in result.content)
