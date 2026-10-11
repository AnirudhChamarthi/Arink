import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services.portfolio_session_store import store


@pytest.mark.asyncio
async def test_enrich_display_omits_returns_and_creates_session():
    body = {
        "portfolio_name": "Test",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
            }
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/enrich?response_detail=display", json=body)

    assert resp.status_code == 200
    data = resp.json()
    assert data["response_detail"] == "display"
    assert "portfolio_session_id" in data
    pos = data["portfolio"]["positions"][0]
    assert "returns_252d" not in pos
    assert "options_chain" not in pos
    assert pos["current_price"] > 0

    full = store.get(data["portfolio_session_id"])
    assert full is not None
    assert len(full.positions[0].returns_252d) == 252


@pytest.mark.asyncio
async def test_var_accepts_portfolio_session_id():
    body = {
        "portfolio_name": "Test",
        "base_currency": "USD",
        "positions": [
            {
                "ticker": "AAPL",
                "asset_class": "Equity",
                "quantity": 10,
                "cost_price": 100,
                "currency": "USD",
            }
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        session_id = enrich.json()["portfolio_session_id"]
        var_resp = await client.post(
            "/risk/var",
            json={
                "portfolio_session_id": session_id,
                "method": "parametric",
                "confidence": 0.99,
                "horizon_days": 1,
            },
        )

    assert var_resp.status_code == 200
    assert var_resp.json()["var"] > 0
