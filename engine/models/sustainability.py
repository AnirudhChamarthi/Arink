"""ESG, carbon VaR, Paris alignment, exclusions, stranded assets."""

from __future__ import annotations

from models.exclusion_policy import exclusion_breaches_for_position
from models.portfolio_utils import position_market_value, position_weights
from schemas.contract import (
    EnrichedPortfolio,
    ExclusionBreach,
    PositionEsgRow,
    SustainabilityResult,
)

_STRANDED_SECTORS = {"energy", "oil", "gas", "coal", "petroleum", "utilities"}
_PARIS_TARGET_CARBON = 100.0  # tCO2e/$M — simplified IEA NZ pathway proxy


def run_sustainability(
    portfolio: EnrichedPortfolio,
    exclusion_filters: list[str] | None = None,
    *,
    include_carbon_var: bool = True,
    carbon_price_shock: float = 50.0,
    run_exclusion_check: bool = True,
) -> SustainabilityResult:
    filters = exclusion_filters or []
    weighted = position_weights(portfolio)
    total_mv = sum(position_market_value(pos) for pos, _ in weighted) or 1.0

    esg_score = 0.0
    carbon_weighted = 0.0
    carbon_var = 0.0
    stranded_mv = 0.0
    per_position: list[PositionEsgRow] = []
    breaches: list[ExclusionBreach] = []

    for pos, weight in weighted:
        esg_score += weight * pos.esg_score
        carbon_weighted += weight * pos.carbon_intensity
        per_position.append(
            PositionEsgRow(
                ticker=pos.ticker,
                esg_score=pos.esg_score,
                carbon_intensity=pos.carbon_intensity,
                weight=weight,
            )
        )

        if include_carbon_var:
            mv = position_market_value(pos)
            carbon_var += (
                mv * pos.carbon_intensity * carbon_price_shock / 1_000_000.0
            ) / total_mv

        sector = (pos.sector or "").lower()
        if any(token in sector for token in _STRANDED_SECTORS):
            stranded_mv += position_market_value(pos)

        if run_exclusion_check and filters:
            breaches.extend(exclusion_breaches_for_position(pos, filters))

    paris_gap = max(0.0, (carbon_weighted - _PARIS_TARGET_CARBON) / _PARIS_TARGET_CARBON * 100.0)
    stranded_pct = stranded_mv / total_mv

    return SustainabilityResult(
        portfolio_esg_score=esg_score,
        carbon_intensity_weighted=carbon_weighted,
        carbon_var=carbon_var,
        paris_alignment_gap_pct=paris_gap,
        exclusion_breaches=breaches,
        stranded_asset_exposure_pct=stranded_pct,
        per_position_esg=sorted(per_position, key=lambda r: -r.weight),
    )


