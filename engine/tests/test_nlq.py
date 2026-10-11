import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_nlq_var_query_with_session_id():
    body = {
        "portfolio_name": "NLQ Test",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
            },
            {
                "ticker": "MSFT",
                "asset_class": "Equity",
                "quantity": 5,
                "cost_price": 200,
                "currency": "USD",
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        assert enrich.status_code == 200
        session_id = enrich.json()["portfolio_session_id"]

        nlq = await client.post(
            "/nlq",
            json={
                "query": "What is my 99% 1-day VaR?",
                "portfolio_session_id": session_id,
                "limits": {"var_limit": 0.05},
            },
        )

    assert nlq.status_code == 200
    data = nlq.json()
    assert data["topline_number"].endswith("%")
    assert data["topline_label"]
    assert len(data["formula_breakdown"]) >= 2
    assert data["explanation"]
    assert data["models_used"]
    assert Path(data["excel_report_path"]).is_file()
    os.remove(data["excel_report_path"])


@pytest.mark.asyncio
async def test_nlq_concentration_keyword():
    body = {
        "portfolio_name": "Conc",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 100,
                "cost_price": 100,
                "currency": "USD",
            },
            {
                "ticker": "MSFT",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        session_id = enrich.json()["portfolio_session_id"]
        nlq = await client.post(
            "/nlq",
            json={
                "query": "What is my largest concentration?",
                "portfolio_session_id": session_id,
                "limits": {"max_concentration": 0.5},
            },
        )

    assert nlq.status_code == 200
    data = nlq.json()
    assert "concentration" in data["models_used"][0]
    assert Path(data["excel_report_path"]).is_file()
    os.remove(data["excel_report_path"])


@pytest.mark.asyncio
async def test_nlq_sustainability_keyword():
    body = {
        "portfolio_name": "ESG",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
                "esg_override": 80,
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        session_id = enrich.json()["portfolio_session_id"]
        nlq = await client.post(
            "/nlq",
            json={
                "query": "What is our portfolio ESG score?",
                "portfolio_session_id": session_id,
                "limits": {"esg_min_score": 50.0},
            },
        )

    assert nlq.status_code == 200
    data = nlq.json()
    assert "sustainability" in data["models_used"][0]
    assert Path(data["excel_report_path"]).is_file()
    os.remove(data["excel_report_path"])
