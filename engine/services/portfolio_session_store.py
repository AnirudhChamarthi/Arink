"""In-memory store of full enriched portfolios keyed by session id (quant use only)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from schemas.contract import EnrichedPortfolio

_DEFAULT_TTL = timedelta(hours=4)


@dataclass
class _SessionEntry:
    portfolio: EnrichedPortfolio
    expires_at: datetime


class PortfolioSessionStore:
    def __init__(self, ttl: timedelta = _DEFAULT_TTL) -> None:
        self._ttl = ttl
        self._sessions: dict[str, _SessionEntry] = {}

    def create(self, portfolio: EnrichedPortfolio) -> str:
        self._purge_expired()
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = _SessionEntry(
            portfolio=portfolio,
            expires_at=datetime.now(timezone.utc) + self._ttl,
        )
        return session_id

    def get(self, session_id: str) -> EnrichedPortfolio | None:
        self._purge_expired()
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        if entry.expires_at <= datetime.now(timezone.utc):
            del self._sessions[session_id]
            return None
        return entry.portfolio

    def _purge_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [sid for sid, e in self._sessions.items() if e.expires_at <= now]
        for sid in expired:
            del self._sessions[sid]


# Process-wide singleton (desktop spawns one engine process per app session).
store = PortfolioSessionStore()
