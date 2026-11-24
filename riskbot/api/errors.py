"""Error model of the REST API: every failure is an ``ErrorBody`` JSON document.

Mapping
-------
| Source                                   | Status                 | ``code``                    |
|------------------------------------------|------------------------|-----------------------------|
| ``RiskbotError`` subclass                | ``exc.http_status``    | ``exc.code``                |
| Request validation (body, path, query)   | 422                    | ``validation_failed``       |
| Body above 10 MB (``limits`` middleware) | 413                    | ``limit_exceeded``          |
| Starlette ``HTTPException`` (404 route,  | its status             | derived from the status     |
| 405 method, ...)                         |                        |                             |
| Any other exception                      | 500                    | ``internal`` (logged only)  |

Unexpected exceptions are logged with their traceback under the ``riskbot.api`` logger; the response
carries only a generic message and a ``request`` hint (method and path), never the exception text.
"""

from __future__ import annotations

import json
import logging
from typing import Any, get_args

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from riskbot.contract.errors import RiskbotError
from riskbot.contract.types import ErrorBody

logger = logging.getLogger("riskbot.api")

_CODES: frozenset[str] = frozenset(get_args(ErrorBody.model_fields["code"].annotation))


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    """Build a JSON response whose body validates as ``ErrorBody``.

    Codes outside the contract's ``ErrorBody.code`` literal are coerced to ``internal`` so a custom
    ``RiskbotError`` subclass can never produce an invalid body.
    """
    if code not in _CODES:
        code = "internal"
    body = ErrorBody(code=code, message=message, details=_jsonable(details or {}))  # type: ignore[arg-type]
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    """Make ``details`` JSON-safe (``str`` fallback for unknown objects)."""
    return json.loads(json.dumps(value, default=str))


def _code_for_status(status: int) -> str:
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 413:
        return "limit_exceeded"
    if 400 <= status < 500:
        return "validation_failed"
    return "internal"


def _clean_validation_errors(errors: Any) -> list[dict[str, Any]]:
    """Reduce pydantic error dicts to ``loc``/``msg``/``type``.

    ``input`` is dropped on purpose: it may be a multi-megabyte dataset and echoing it back is wasteful;
    ``ctx`` may hold exception objects that are not JSON-serialisable.
    """
    out = []
    for err in errors:
        out.append({"loc": [str(p) if not isinstance(p, int) else p for p in err.get("loc", ())],
                    "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))})
    return out


async def _riskbot_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RiskbotError)
    if exc.http_status >= 500:
        logger.error("service error on %s %s: %s", request.method, request.url.path, exc.message)
    return error_response(exc.http_status, exc.code, exc.message, exc.details)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = _clean_validation_errors(exc.errors())
    first = errors[0] if errors else None
    msg = "request validation failed"
    if first:
        msg += f": {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
    return error_response(422, "validation_failed", msg, {"errors": errors})


async def _http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    response = error_response(exc.status_code, _code_for_status(exc.status_code), str(exc.detail))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def install_error_handlers(app: FastAPI) -> None:
    """Register the ``ErrorBody`` exception handlers on ``app``."""
    app.add_exception_handler(RiskbotError, _riskbot_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_exception)


class InternalErrorMiddleware:
    """Pure ASGI middleware turning any unhandled exception into ``500 internal``.

    It sits inside the CORS middleware so browsers still see CORS headers on 500 responses (Starlette's
    own ``ServerErrorMiddleware`` is outermost and would skip them). The traceback is logged; the client
    gets no internal detail. If the response had already started, the exception is re-raised.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            method, path = scope.get("method", "?"), scope.get("path", "?")
            logger.exception("unhandled error on %s %s", method, path)
            if started:
                raise
            response = error_response(
                500, "internal", "internal server error", {"request": f"{method} {path}"}
            )
            await response(scope, receive, send)
