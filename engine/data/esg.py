"""ESG and carbon intensity from bundled sample datasets (+ optional Yahoo supplement)."""

from __future__ import annotations

import csv
from pathlib import Path

from data.cache import cache_get, cache_set

_DATA_DIR = Path(__file__).resolve().parent
_ESG_PATH = _DATA_DIR / "sample_esg.csv"
_CARBON_PATH = _DATA_DIR / "sample_carbon.csv"

_DEFAULT_ESG = 50.0
_DEFAULT_CARBON = 75.0


def _load_csv_map(path: Path, value_column: str) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"].strip().upper()
            out[ticker] = float(row[value_column])
    return out


def _load_tags(path: Path) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"].strip().upper()
            raw = row.get("sector_tags", "")
            tags[ticker] = {t.strip().lower() for t in raw.split("|") if t.strip()}
    return tags


def _esg_table() -> dict[str, float]:
    key = "esg_table_v1"
    cached = cache_get(key)
    if cached is not None:
        return cached
    table = _load_csv_map(_ESG_PATH, "esg_score")
    cache_set(key, table, ttl_seconds=24 * 60 * 60)
    return table


def _carbon_table() -> dict[str, float]:
    key = "carbon_table_v1"
    cached = cache_get(key)
    if cached is not None:
        return cached
    table = _load_csv_map(_CARBON_PATH, "carbon_intensity_tco2e_per_m_usd")
    cache_set(key, table, ttl_seconds=24 * 60 * 60)
    return table


def sector_tags() -> dict[str, set[str]]:
    key = "sector_tags_v1"
    cached = cache_get(key)
    if cached is not None:
        return cached
    tags = _load_tags(_ESG_PATH)
    cache_set(key, tags, ttl_seconds=24 * 60 * 60)
    return tags


def fetch_esg_score(ticker: str, override: float | None = None) -> float:
    if override is not None:
        return float(override)
    return _esg_table().get(ticker.upper(), _DEFAULT_ESG)


def fetch_carbon_intensity(ticker: str) -> float:
    return _carbon_table().get(ticker.upper(), _DEFAULT_CARBON)
