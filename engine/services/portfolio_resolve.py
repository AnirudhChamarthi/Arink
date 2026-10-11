"""Resolve full EnrichedPortfolio from session id or inline body."""

from __future__ import annotations

from schemas.contract import EnrichedPortfolio
from services.portfolio_session_store import store


def resolve_enriched_portfolio(
    *,
    portfolio_session_id: str | None,
    portfolio: EnrichedPortfolio | None,
) -> EnrichedPortfolio:
    if portfolio_session_id:
        cached = store.get(portfolio_session_id)
        if cached is None:
            raise ValueError(
                f"Unknown or expired portfolio_session_id: {portfolio_session_id}"
            )
        return cached
    if portfolio is not None:
        return portfolio
    raise ValueError("Provide portfolio_session_id or portfolio in request body.")
