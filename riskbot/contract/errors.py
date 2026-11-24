"""Errors every component raises at its boundary. Adapters map them to HTTP / MCP errors."""

from __future__ import annotations

from typing import Any


class RiskbotError(Exception):
    code = "internal"
    http_status = 500

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(RiskbotError):
    code = "not_found"
    http_status = 404


class ValidationFailed(RiskbotError):
    code = "validation_failed"
    http_status = 422


class Conflict(RiskbotError):
    """The request is valid but not allowed in the current state (e.g. reviewing a running run)."""

    code = "conflict"
    http_status = 409


class LimitExceeded(RiskbotError):
    code = "limit_exceeded"
    http_status = 413
