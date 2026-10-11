"""Disk cache for enrichment and market data (4-hour default TTL)."""

from __future__ import annotations

import os
from pathlib import Path

import diskcache

_DEFAULT_TTL_SECONDS = 4 * 60 * 60
_CACHE: diskcache.Cache | None = None


def cache_dir() -> Path:
    env = os.environ.get("RISKBOT_CACHE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / ".cache"


def get_cache() -> diskcache.Cache:
    global _CACHE
    if _CACHE is None:
        path = cache_dir()
        path.mkdir(parents=True, exist_ok=True)
        _CACHE = diskcache.Cache(str(path))
    return _CACHE


def cache_get(key: str):
    return get_cache().get(key, default=None)


def cache_set(key: str, value, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
    get_cache().set(key, value, expire=ttl_seconds)
