"""Illustrative scenario and reference tables for the Q3 transition-risk model.

EVERY number in this module is ILLUSTRATIVE. The carbon-price paths are shaped like the NGFS scenario
families (orderly / disorderly / hot house world) but are not NGFS data; the pass-through rates, sector
intensities and benchmark pathway are round numbers chosen to give plausible magnitudes for a teaching
portfolio. They are collected in one frozen dataclass so that

* the model documentation (README.md) can list them in one place,
* tests can substitute alternative assumptions (zero carbon price, full pass-through) and check the
  closed-form consequences, and
* a production user would replace them with sourced data without touching the maths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

SCENARIOS = ("orderly", "disorderly", "hot_house")

SECTORS = (
    "energy", "utilities", "materials", "industrials", "transportation", "consumer",
    "technology", "financials", "health_care", "real_estate", "other",
)


def _ro(d: dict) -> Mapping:
    return MappingProxyType(dict(d))


def carbon_price(scenario: str, t: int) -> float:
    """Unscaled carbon price (USD/tCO2e, illustrative) ``t`` years after the as-of year (t = 0 is as-of).

    * orderly:    P(t) = 60 + 10 t for t <= 9 (60 -> 150 linearly over 9 years), then 150 + 5 (t - 9).
    * disorderly: P(t) = 35 for t <= 3 (flat for 4 years, t = 0..3), then a linear jump
                  35 + (250 - 35)(t - 3)/3 for 3 < t <= 6, then 250 flat.
    * hot_house:  P(t) = 35 + t.
    """
    if t < 0:
        raise ValueError("t must be >= 0")
    if scenario == "orderly":
        return 60.0 + 10.0 * t if t <= 9 else 150.0 + 5.0 * (t - 9)
    if scenario == "disorderly":
        if t <= 3:
            return 35.0
        if t <= 6:
            return 35.0 + (250.0 - 35.0) * (t - 3) / 3.0
        return 250.0
    if scenario == "hot_house":
        return 35.0 + float(t)
    raise ValueError(f"unknown scenario {scenario!r}")


@dataclass(frozen=True)
class SectorReference:
    """Illustrative sector reference intensities in tCO2e (scope 1+2) per USD million of revenue."""

    median: float  # fallback central intensity used when no reported peer exists
    p75: float  # fallback 75th percentile used by the `conservative` treatment
    benchmark_2020: float  # 2020 benchmark intensity used for the alignment pathway


@dataclass(frozen=True)
class TransitionAssumptions:
    """All illustrative parameters of q3.transition in one place (see README.md, section Parameters)."""

    price_multipliers: Mapping[str, float] = field(
        default_factory=lambda: _ro({"low": 0.5, "central": 1.0, "high": 2.0}))
    pass_through: Mapping[str, float] = field(default_factory=lambda: _ro({
        "energy": 0.3, "utilities": 0.5, "materials": 0.3, "industrials": 0.4, "transportation": 0.4,
        "consumer": 0.6, "technology": 0.8, "financials": 0.8, "health_care": 0.8, "real_estate": 0.5,
        "other": 0.5,
    }))
    discount_rate: float = 0.05
    # Log-normal spread of emissions by data-quality score (PCAF-style 1 best .. 5 worst); imputed: 0.60.
    sigma_by_quality: Mapping[int, float] = field(
        default_factory=lambda: _ro({1: 0.05, 2: 0.10, 3: 0.20, 4: 0.35, 5: 0.50}))
    sigma_imputed: float = 0.60
    sector_reference: Mapping[str, SectorReference] = field(default_factory=lambda: _ro({
        "energy": SectorReference(550.0, 900.0, 600.0),
        "utilities": SectorReference(1400.0, 2600.0, 1500.0),
        "materials": SectorReference(700.0, 1300.0, 800.0),
        "industrials": SectorReference(120.0, 250.0, 150.0),
        "transportation": SectorReference(400.0, 750.0, 450.0),
        "consumer": SectorReference(50.0, 110.0, 60.0),
        "technology": SectorReference(12.0, 30.0, 15.0),
        "financials": SectorReference(8.0, 20.0, 10.0),
        "health_care": SectorReference(20.0, 45.0, 25.0),
        "real_estate": SectorReference(70.0, 150.0, 80.0),
        "other": SectorReference(100.0, 250.0, 120.0),
    }))
    pathway_base_year: int = 2020
    pathway_decline: float = 0.07  # annual intensity reduction of the budget pathway
    # Optional override of the carbon-price function (tests use it for a zero price).
    price_override: float | None = None
    low_threshold: float = 0.02  # exposure_level low if loss_pct < 2%
    moderate_threshold: float = 0.08  # moderate if < 8%, else high

    def price(self, scenario: str, t: int, price_path: str) -> float:
        """Scaled carbon price m * P(t) in USD/tCO2e."""
        base = carbon_price(scenario, t) if self.price_override is None else self.price_override
        return self.price_multipliers[price_path] * base

    def sigma(self, data_quality: int | None, imputed: bool) -> float:
        if imputed:
            return self.sigma_imputed
        return self.sigma_by_quality[5 if data_quality is None else int(data_quality)]

    def pathway_factor(self, as_of_year: int) -> float:
        """(1 - d)^(as_of_year - base_year)."""
        return (1.0 - self.pathway_decline) ** (as_of_year - self.pathway_base_year)

    def with_(self, **changes) -> "TransitionAssumptions":
        return replace(self, **changes)


DEFAULT_ASSUMPTIONS = TransitionAssumptions()

assert all(math.isfinite(v) for v in DEFAULT_ASSUMPTIONS.pass_through.values())
assert set(DEFAULT_ASSUMPTIONS.pass_through) == set(SECTORS) == set(DEFAULT_ASSUMPTIONS.sector_reference)


def normalise_sector(sector: str) -> tuple[str, bool]:
    """Lower-case, trim and map spaces/hyphens to underscores. Returns (sector, known)."""
    s = sector.strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in s:
        s = s.replace("__", "_")
    if s in SECTORS:
        return s, True
    return "other", False
