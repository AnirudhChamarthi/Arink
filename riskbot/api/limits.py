"""Input limits enforced at the HTTP boundary, before any work reaches the ``RunService``.

Two layers:

* :class:`BodySizeLimitMiddleware` (pure ASGI) rejects any request body larger than
  :data:`MAX_BODY_BYTES` with ``413 limit_exceeded``. It checks ``Content-Length`` first and also counts
  the bytes actually streamed, so chunked uploads without a length header are capped too.
* :func:`check_dataset_limits` and :func:`check_plan_limits` apply ``catalog.LIMITS`` to parsed
  datasets and plans and raise :class:`~riskbot.contract.errors.LimitExceeded`, which the error handlers
  map to ``413``. The services re-check the same limits; checking here keeps oversized work off the
  service thread pool entirely.
"""

from __future__ import annotations

import json
import math
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from riskbot.contract import catalog
from riskbot.contract.errors import LimitExceeded
from riskbot.contract.types import (
    BankBalanceSheet,
    ClimatePortfolio,
    Dataset,
    ErrorBody,
    MarketDataset,
    QuestionPlan,
)

MAX_BODY_BYTES = 10 * 1024 * 1024
"""Largest accepted request body (10 MB)."""


def _exceeded(what: str, value: int, limit_key: str) -> None:
    """Raise ``LimitExceeded`` if ``value`` is above ``catalog.LIMITS[limit_key]``."""
    maximum = catalog.LIMITS[limit_key]
    if value > maximum:
        raise LimitExceeded(
            f"{what} is {value}, above the limit of {maximum}", limit=limit_key, value=value, maximum=maximum
        )


def check_dataset_limits(dataset: Dataset) -> None:
    """Apply ``catalog.LIMITS`` to a dataset.

    * market: ``len(positions) <= max_positions`` and ``len(dates) <= max_history_days``;
    * balance sheet: assets + loan pools + deposit segments + wholesale lines + hedges
      ``<= max_balance_sheet_items``;
    * climate: ``len(holdings) <= max_holdings``.

    Raises:
        LimitExceeded: with ``details = {"limit", "value", "maximum"}``.
    """
    if isinstance(dataset, MarketDataset):
        _exceeded("number of positions", len(dataset.positions), "max_positions")
        _exceeded("length of the return history", len(dataset.dates), "max_history_days")
    elif isinstance(dataset, BankBalanceSheet):
        items = (
            len(dataset.assets)
            + len(dataset.loan_pools)
            + len(dataset.deposits)
            + len(dataset.wholesale_funding)
            + len(dataset.hedges)
        )
        _exceeded("number of balance-sheet items", items, "max_balance_sheet_items")
    elif isinstance(dataset, ClimatePortfolio):
        _exceeded("number of holdings", len(dataset.holdings), "max_holdings")


def plan_size(plan: QuestionPlan) -> int:
    """Upper bound on the variations a plan expands to: product of grid dimension sizes plus extras.

    The planner may collapse duplicates (``applies_when``), so the real count can be lower; the bound is
    what matters for rejecting obviously oversized plans cheaply.
    """
    dims = plan.grid.dimensions
    grid = math.prod(len(v) for v in dims.values()) if dims else 1
    return grid + len(plan.extras)


def check_plan_limits(plan: QuestionPlan | None) -> None:
    """Reject a plan whose upper-bound size exceeds ``catalog.LIMITS["max_variations"]``."""
    if plan is not None:
        _exceeded("number of planned variations", plan_size(plan), "max_variations")


def _error_body_bytes(message: str, **details: Any) -> bytes:
    body = ErrorBody(code="limit_exceeded", message=message, details=details)
    return json.dumps(body.model_dump(mode="json")).encode()


class BodySizeLimitMiddleware:
    """Pure ASGI middleware that buffers the request body up to ``max_bytes`` and rejects anything larger.

    The body is read completely before the application runs and then replayed, so the application never
    sees a partial body and the 413 response is sent before any route code executes.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                declared = -1
            if declared > self.max_bytes:
                await self._reject(send, declared)
                return

        # Buffer the streamed body, counting bytes as they arrive.
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break  # e.g. http.disconnect
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(send, total)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send: Send, size: int) -> None:
        body = _error_body_bytes(
            f"request body of {size} bytes exceeds the limit of {self.max_bytes} bytes",
            limit="max_body_bytes",
            value=size,
            maximum=self.max_bytes,
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
