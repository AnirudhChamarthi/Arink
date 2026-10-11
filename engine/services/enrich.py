"""Portfolio enrichment orchestration."""

from __future__ import annotations

import logging

from data import esg, market
from schemas.contract import (
    EnrichRequest,
    EnrichResponse,
    EnrichedPortfolio,
    EnrichedPortfolioDisplay,
    EnrichedPosition,
    EnrichedPositionDisplay,
    RawPosition,
    ResponseDetail,
)
from services.portfolio_session_store import store

logger = logging.getLogger(__name__)


def _resolve_ticker(pos: RawPosition) -> str:
    ticker = pos.ticker.strip().upper()
    if ticker:
        return ticker
    if pos.isin:
        mapped = market.resolve_ticker_from_isin(pos.isin)
        if mapped:
            return mapped.upper()
    raise ValueError(f"Cannot resolve ticker for position (isin={pos.isin})")


def enrich_position(pos: RawPosition, risk_free_rate: float) -> EnrichedPosition:
    ticker = _resolve_ticker(pos)
    mkt = market.fetch_ticker_market_data(ticker, risk_free_rate)
    options_chain = market.fetch_options_chain(ticker, mkt["current_price"])
    has_options = options_chain is not None

    return EnrichedPosition(
        ticker=ticker,
        isin=pos.isin,
        asset_class=pos.asset_class,
        quantity=pos.quantity,
        cost_price=pos.cost_price,
        currency=pos.currency,
        sector=pos.sector,
        country=pos.country,
        esg_override=pos.esg_override,
        name=mkt["name"],
        current_price=mkt["current_price"],
        returns_252d=mkt["returns_252d"],
        implied_vol=mkt["implied_vol"],
        risk_free_rate=risk_free_rate,
        esg_score=esg.fetch_esg_score(ticker, pos.esg_override),
        carbon_intensity=esg.fetch_carbon_intensity(ticker),
        market_cap=mkt.get("market_cap"),
        beta=mkt.get("beta"),
        has_options=has_options,
        options_chain=options_chain,
    )


def enrich_portfolio(request: EnrichRequest) -> EnrichedPortfolio:
    risk_free_rate = market.fetch_risk_free_rate()
    enriched: list[EnrichedPosition] = []
    for pos in request.positions:
        try:
            enriched.append(enrich_position(pos, risk_free_rate))
        except Exception as exc:
            logger.exception("Enrichment failed for %s", pos.ticker)
            raise ValueError(f"Failed to enrich {pos.ticker}: {exc}") from exc

    return EnrichedPortfolio(
        portfolio_name=request.portfolio_name,
        base_currency=request.base_currency,
        benchmark=request.benchmark,
        positions=enriched,
    )


def _to_display_position(pos: EnrichedPosition) -> EnrichedPositionDisplay:
    return EnrichedPositionDisplay(
        ticker=pos.ticker,
        isin=pos.isin,
        asset_class=pos.asset_class,
        quantity=pos.quantity,
        cost_price=pos.cost_price,
        currency=pos.currency,
        sector=pos.sector,
        country=pos.country,
        esg_override=pos.esg_override,
        name=pos.name,
        current_price=pos.current_price,
        implied_vol=pos.implied_vol,
        risk_free_rate=pos.risk_free_rate,
        esg_score=pos.esg_score,
        carbon_intensity=pos.carbon_intensity,
        market_cap=pos.market_cap,
        beta=pos.beta,
        has_options=pos.has_options,
    )


def to_display_portfolio(portfolio: EnrichedPortfolio) -> EnrichedPortfolioDisplay:
    return EnrichedPortfolioDisplay(
        portfolio_name=portfolio.portfolio_name,
        base_currency=portfolio.base_currency,
        benchmark=portfolio.benchmark,
        positions=[_to_display_position(p) for p in portfolio.positions],
    )


def enrich_and_respond(
    request: EnrichRequest, response_detail: ResponseDetail
) -> EnrichResponse:
    full = enrich_portfolio(request)
    session_id = store.create(full)
    if response_detail == ResponseDetail.FULL:
        body: EnrichedPortfolio | EnrichedPortfolioDisplay = full
    else:
        body = to_display_portfolio(full)
    return EnrichResponse(
        portfolio_session_id=session_id,
        response_detail=response_detail,
        portfolio=body,
    )
