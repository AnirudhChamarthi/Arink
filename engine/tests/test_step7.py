import os
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.greeks import run_greeks
from models.stress import run_stress
from models.sustainability import run_sustainability
from models.var import historical_var, montecarlo_var
from schemas.contract import (
    AssetClass,
    EnrichedPortfolio,
    EnrichedPosition,
    StressScenario,
    VarMethod,
)


def _position(ticker: str, qty: float = 10.0, sector: str = "Technology") -> EnrichedPosition:
    rng = np.random.default_rng(hash(ticker) % 2**32)
    returns = rng.normal(0.0002, 0.012, 252).tolist()
    return EnrichedPosition(
        ticker=ticker,
        asset_class=AssetClass.EQUITY,
        quantity=qty,
        cost_price=90.0,
        currency="USD",
        sector=sector,
        current_price=100.0,
        returns_252d=returns,
        implied_vol=0.25,
        risk_free_rate=0.04,
        esg_score=70.0,
        carbon_intensity=80.0,
        beta=1.1,
    )


def _portfolio() -> EnrichedPortfolio:
    return EnrichedPortfolio(
        portfolio_name="Step7",
        base_currency="USD",
        positions=[_position("AAPL"), _position("XOM", sector="Energy")],
    )


def test_historical_and_montecarlo_var():
    portfolio = _portfolio()
    hist = historical_var(portfolio, 0.99, 1)
    mc = montecarlo_var(portfolio, 0.99, 1, n_sims=500)
    assert hist.method == VarMethod.HISTORICAL
    assert mc.method == VarMethod.MONTECARLO
    assert hist.var > 0
    assert mc.var > 0


def test_greeks_stress_sustainability_models():
    portfolio = _portfolio()
    greeks = run_greeks(portfolio)
    assert len(greeks.positions) == 2
    assert greeks.portfolio_delta != 0.0

    stress = run_stress(portfolio, StressScenario.CREDIT_2008)
    assert stress.scenario == "2008_credit"
    assert stress.portfolio_pnl < 0
    assert len(stress.worst_positions) <= 5

    esg = run_sustainability(portfolio, ["fossil_fuels"], include_carbon_var=True)
    assert esg.portfolio_esg_score > 0
    assert esg.carbon_var >= 0


@pytest.mark.asyncio
async def test_risk_endpoints_with_session():
    body = {
        "portfolio_name": "Step7 API",
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
            {
                "ticker": "XOM",
                "asset_class": "Equity",
                "quantity": 5,
                "cost_price": 90,
                "currency": "USD",
                "sector": "Energy",
            },
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        enrich = await client.post("/enrich?response_detail=display", json=body)
        assert enrich.status_code == 200
        sid = enrich.json()["portfolio_session_id"]

        greeks = await client.post("/risk/greeks", json={"portfolio_session_id": sid})
        assert greeks.status_code == 200
        assert len(greeks.json()["positions"]) == 2

        stress = await client.post(
            "/risk/stress",
            json={"portfolio_session_id": sid, "scenario": "covid_2020"},
        )
        assert stress.status_code == 200
        assert stress.json()["scenario"] == "covid_2020"

        sustain = await client.post(
            "/risk/sustainability",
            json={
                "portfolio_session_id": sid,
                "exclusion_filters": ["fossil_fuels"],
                "include_carbon_var": True,
            },
        )
        assert sustain.status_code == 200
        assert "portfolio_esg_score" in sustain.json()

        garch = await client.post(
            "/risk/garch",
            json={"portfolio_session_id": sid, "ticker": "AAPL"},
        )
        assert garch.status_code == 200
        assert garch.json()["ticker"] == "AAPL"

        hist_var = await client.post(
            "/risk/var",
            json={
                "portfolio_session_id": sid,
                "method": "historical",
                "confidence": 0.99,
                "horizon_days": 1,
            },
        )
        assert hist_var.status_code == 200
        assert hist_var.json()["method"] == "historical"

        nlq = await client.post(
            "/nlq",
            json={
                "query": "What is our portfolio delta?",
                "portfolio_session_id": sid,
                "limits": {},
            },
        )
    assert nlq.status_code == 200
    assert "greeks" in nlq.json()["models_used"][0]
    assert Path(nlq.json()["excel_report_path"]).is_file()
    os.remove(nlq.json()["excel_report_path"])
