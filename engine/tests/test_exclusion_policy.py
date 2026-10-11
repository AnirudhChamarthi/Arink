"""Custom ESG exclusion policy — tickers vs presets."""

import numpy as np

from models.exclusion_policy import exclusion_breaches_for_position, parse_exclusion_filters
from schemas.contract import AssetClass, EnrichedPosition


def _pos(ticker: str, name: str, sector: str) -> EnrichedPosition:
    return EnrichedPosition(
        ticker=ticker,
        name=name,
        asset_class=AssetClass.EQUITY,
        quantity=10,
        cost_price=100,
        currency="USD",
        sector=sector,
        current_price=100,
        returns_252d=np.zeros(252).tolist(),
        implied_vol=0.2,
        risk_free_rate=0.04,
        esg_score=50,
        carbon_intensity=10,
    )


def test_ticker_only_excludes_palantir_not_boeing():
    filters = ["ticker:PLTR"]
    pltr = exclusion_breaches_for_position(
        _pos("PLTR", "Palantir Technologies Inc.", "Technology"), filters
    )
    boeing = exclusion_breaches_for_position(
        _pos("BA", "Boeing Company", "Aerospace"), filters
    )
    assert len(pltr) == 1
    assert len(boeing) == 0


def test_weapons_preset_off_allows_aerospace():
    filters = ["ticker:PLTR"]
    anduril = exclusion_breaches_for_position(
        _pos("ANDUR", "Anduril Industries", "Aerospace & Defense"), filters
    )
    assert len(anduril) == 0


def test_weapons_preset_flags_defense_sector():
    filters = ["weapons"]
    boeing = exclusion_breaches_for_position(
        _pos("BA", "Boeing Company", "Aerospace"), filters
    )
    assert len(boeing) == 1
    assert boeing[0].filter == "weapons"


def test_name_keyword_matches():
    filters = ["name:palantir"]
    hits = exclusion_breaches_for_position(
        _pos("PLTR", "Palantir Technologies Inc.", "Technology"), filters
    )
    assert len(hits) == 1
    assert "palantir" in hits[0].filter


def test_parse_bare_ticker():
    policy = parse_exclusion_filters(["PLTR", "fossil_fuels"])
    assert "PLTR" in policy.excluded_tickers
    assert "fossil_fuels" in policy.preset_filters
