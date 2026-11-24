"""Riskbot v2 REST API: a FastAPI adapter over ``contract.ports.RunService``.

Export: :func:`create_app`. The composition root (``python -m riskbot.app api``) builds the service,
calls ``create_app(service)`` and serves the result. See ``README.md`` for routes and the error model.
"""

from .app import create_app

__all__ = ["create_app"]
