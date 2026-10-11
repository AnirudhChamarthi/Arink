"""Riskbot Python engine — FastAPI entrypoint."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI

# Ensure engine root is on sys.path when launched as `python main.py` or uvicorn main:app
_ENGINE_ROOT = Path(__file__).resolve().parent
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))


def _load_repo_env() -> None:
    """Load repo-root `.env` so ANTHROPIC_API_KEY etc. are available without manual export."""
    env_path = _ENGINE_ROOT.parent / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:
        logging.getLogger(__name__).warning(
            "python-dotenv not installed; set environment variables manually or pip install -r requirements.txt"
        )


_load_repo_env()

from api.routes import enrich, health, nlq, risk  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Riskbot Engine API",
    version="1.0.0",
    description="Quantitative risk engine for Riskbot desktop client.",
)

app.include_router(health.router)
app.include_router(enrich.router)
app.include_router(nlq.router)
app.include_router(risk.router)


@app.get("/")
def root():
    return {"service": "riskbot-engine", "docs": "/docs"}
