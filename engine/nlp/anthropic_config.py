"""Anthropic API settings for NLQ routing and explanations."""

from __future__ import annotations

import os

# Default Sonnet model — override with ANTHROPIC_MODEL in .env if your account differs.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


def anthropic_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL).strip() or DEFAULT_ANTHROPIC_MODEL
