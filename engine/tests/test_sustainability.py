"""Sustainability endpoint and NLQ — schema completeness."""

import os
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.sustainability import run_sustainability
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _position(ticker: str, sector: str, esg: float, carbon: float) -> EnrichedPosition:
    return EnrichedPosition(
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=10.0,
        cost_price=100.0,
        currency="USD",
        sector=sector,
        current_price=100.0,
        returns_252d=np.random.default_rng(1).normal(0, 0.01, 252).tolist(),
        implied_vol=0.2,
        risk_free_rate=0.04,
        esg_score=esg,
        carbon_intensity=carbon,
    )


def test_sustainability_result_has_all_openapi_fields():
    portfolio = EnrichedPortfolio(
        portfolio_name="ESG",
        base_currency="USD",
        positions=[
            _position("AAPL", "Technology", 80.0, 30.0),
            _position("XOM", "Energy", 40.0, 200.0),
        ],
    )
    result = run_sustainability(
        portfolio,
        ["fossil_fuels"],
        include_carbon_var=True,
        carbon_price_shock=50.0,
        run_exclusion_check=True,
    )

    assert result.portfolio_esg_score > 0
    assert result.carbon_intensity_weighted > 0
    assert result.carbon_var >= 0
    assert result.paris_alignment_gap_pct >= 0
    assert result.stranded_asset_exposure_pct > 0
    assert len(result.per_position_esg) == 2
    assert any(b.ticker == "XOM" and b.filter == "fossil_fuels" for b in result.exclusion_breaches)


@pytest.mark.asyncio
async def test_sustainability_endpoint_via_session():
    body = {
        "portfolio_name": "ESG API",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "XOM",
                "asset_class": "Equity",
                "quantity": 50,
                "cost_price": 90,
                "currency": "USD",
                "sector": "Energy",
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        sid = enrich.json()["portfolio_session_id"]
        resp = await client.post(
            "/risk/sustainability",
            json={
                "portfolio_session_id": sid,
                "exclusion_filters": ["fossil_fuels"],
                "include_carbon_var": True,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "portfolio_esg_score",
        "carbon_intensity_weighted",
        "carbon_var",
        "paris_alignment_gap_pct",
        "exclusion_breaches",
        "stranded_asset_exposure_pct",
        "per_position_esg",
    ):
        assert key in data


@pytest.mark.asyncio
async def test_nlq_sustainability_includes_carbon_var_in_formula():
    body = {
        "portfolio_name": "NLQ ESG",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
                "sector": "Technology",
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        sid = enrich.json()["portfolio_session_id"]
        nlq = await client.post(
            "/nlq",
            json={
                "query": "What is our carbon VaR and ESG score?",
                "portfolio_session_id": sid,
                "limits": {},
            },
        )

    assert nlq.status_code == 200
    data = nlq.json()
    assert "sustainability" in data["models_used"][0]
    formula = " ".join(data["formula_breakdown"]).lower()
    assert "carbon" in formula
    assert Path(data["excel_report_path"]).is_file()
    os.remove(data["excel_report_path"])
