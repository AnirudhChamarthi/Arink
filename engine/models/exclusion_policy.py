"""Parse and apply user-defined ESG / exclusion preferences."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from schemas.contract import EnrichedPosition, ExclusionBreach

PRESET_FILTERS = frozenset({"weapons", "tobacco", "fossil_fuels", "gambling"})

_PRESET_SECTOR_MAP: dict[str, list[str]] = {
    "weapons": ["defense", "aerospace", "weapons", "military"],
    "tobacco": ["tobacco"],
    "fossil_fuels": ["energy", "oil", "gas", "coal", "petroleum"],
    "gambling": ["casino", "gambling"],
}

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,19}$")
_MAX_FILTER_TOKENS = 500
_MAX_KEYWORD_LEN = 64


@dataclass
class ExclusionPolicy:
    preset_filters: list[str] = field(default_factory=list)
    excluded_tickers: set[str] = field(default_factory=set)
    name_keywords: list[str] = field(default_factory=list)
    sector_keywords: list[str] = field(default_factory=list)


def parse_exclusion_filters(filters: list[str] | None) -> ExclusionPolicy:
    policy = ExclusionPolicy()
    for raw in filters or []:
        token = raw.strip()
        if not token:
            continue
        lower = token.lower()
        if lower.startswith("ticker:"):
            policy.excluded_tickers.add(token.split(":", 1)[1].strip().upper())
            continue
        if lower.startswith("name:"):
            kw = token.split(":", 1)[1].strip().lower()[:_MAX_KEYWORD_LEN]
            if kw:
                policy.name_keywords.append(kw)
            continue
        if lower.startswith("sector:"):
            for part in token.split(":", 1)[1].split(","):
                kw = part.strip().lower()
                if kw:
                    policy.sector_keywords.append(kw)
            continue
        if lower.startswith("preset:"):
            for part in token.split(":", 1)[1].split(","):
                key = part.strip().lower()
                if key in PRESET_FILTERS:
                    policy.preset_filters.append(key)
            continue
        if lower in PRESET_FILTERS:
            policy.preset_filters.append(lower)
            continue
        if _TICKER_RE.match(token.upper()):
            policy.excluded_tickers.add(token.upper())
            continue
        policy.sector_keywords.append(lower.replace(" ", "_"))
    return policy


def exclusion_breaches_for_position(
    pos: EnrichedPosition,
    filters: list[str] | None,
) -> list[ExclusionBreach]:
    policy = parse_exclusion_filters(filters)
    ticker = pos.ticker.upper()
    name = (getattr(pos, "name", None) or "").lower()
    sector = (pos.sector or "").lower()
    found: list[ExclusionBreach] = []

    for t in policy.excluded_tickers:
        if ticker == t:
            found.append(
                ExclusionBreach(
                    ticker=pos.ticker,
                    filter=f"ticker:{t}",
                    reason=f"Ticker {pos.ticker} is on your exclusion list.",
                )
            )
            break

    for kw in policy.name_keywords:
        if kw and kw in name:
            found.append(
                ExclusionBreach(
                    ticker=pos.ticker,
                    filter=f"name:{kw}",
                    reason=f"Company name matches excluded keyword '{kw}'.",
                )
            )
            break

    for preset in policy.preset_filters:
        tokens = _PRESET_SECTOR_MAP.get(preset, [])
        if any(token in sector for token in tokens):
            found.append(
                ExclusionBreach(
                    ticker=pos.ticker,
                    filter=preset,
                    reason=f"Sector '{pos.sector}' matches preset exclusion '{preset}'.",
                )
            )
            break

    for kw in policy.sector_keywords:
        if kw.replace("_", " ") in sector or kw in sector:
            found.append(
                ExclusionBreach(
                    ticker=pos.ticker,
                    filter=f"sector:{kw}",
                    reason=f"Sector '{pos.sector}' matches custom keyword '{kw}'.",
                )
            )
            break

    return found
