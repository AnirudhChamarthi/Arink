"""Oracles for q3.data_quality and the design properties of sample_dataset()."""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest

from riskbot.contract import catalog
from riskbot.contract.conformance import check_output
from riskbot.contract.types import ClimateHolding, ClimatePortfolio
from riskbot.core.climate import DataQualityModel, models, sample_dataset
from riskbot.core.climate.assumptions import normalise_sector
from riskbot.core.climate.data_quality import quality_label

SPEC = catalog.Q3_DATA_QUALITY


def _book():
    return ClimatePortfolio(name="dq", as_of=dt.date(2026, 6, 30), synthetic=True, holdings=[
        ClimateHolding(issuer="A", sector="energy", market_value=200, evic=1e9, revenue=1e8, scope1=1, scope2=1,
                       scope3=5, data_quality=1, emissions_year=2025, controversy_flags=["spill"]),
        ClimateHolding(issuer="B", sector="technology", market_value=500, evic=1e9, revenue=1e8, scope1=1,
                       scope2=1, data_quality=3, emissions_year=2023),  # stale with stale_years=2 (< 2024)
        ClimateHolding(issuer="C", sector="Widgets", market_value=300, evic=1e9, revenue=1e8,
                       data_quality=2, exclusion_flags=["coal"]),  # missing scope 1/2 -> quality 5
        ClimateHolding(issuer="S", sector="energy", market_value=-400, evic=1e9, revenue=1e8,
                       controversy_flags=["x"]),
    ])


def test_hand_computed_metrics_and_findings():
    out = DataQualityModel().run(_book(), {}, 0)
    assert check_output(SPEC, out) == []
    m = {k: v.value for k, v in out.metrics.items()}
    # long MV 1000: weights .2 / .5 / .3; the short only appears in findings
    assert m["coverage_scope12"] == pytest.approx(0.7)
    assert m["coverage_scope3"] == pytest.approx(0.2)
    assert m["mean_data_quality"] == pytest.approx(0.2 * 1 + 0.5 * 3 + 0.3 * 5)
    assert m["stale_share"] == pytest.approx(0.5)
    assert m["controversy_share"] == pytest.approx(0.2)
    assert out.labels["quality"] == "fair"
    checks = Counter((f.check, f.subject) for f in out.findings)
    assert checks[("missing_scope12", "C")] == 1 and checks[("missing_scope12", "S")] == 1
    assert checks[("stale_emissions", "B")] == 1 and checks[("exclusion_breach", "C")] == 1
    assert checks[("unknown_sector", "C")] == 1 and checks[("controversy", "A")] == 1
    assert sum(1 for f in out.findings if f.check == "missing_scope3") == 3
    # stale_years=3 -> cutoff 2023 -> B no longer stale
    assert DataQualityModel().run(_book(), {"stale_years": 3}, 0).metrics["stale_share"].value == 0.0


def test_quality_label_rules():
    assert quality_label(0.59, 0.0) == "poor"
    assert quality_label(0.84, 0.0) == "fair"
    assert quality_label(0.90, 0.21) == "fair"
    assert quality_label(0.90, 0.20) == "good"
    assert quality_label(0.85, 0.0) == "good"


def test_sample_dataset_design():
    ds = sample_dataset()
    assert ds.synthetic and ds.as_of == dt.date(2026, 10, 30) and ds.kind == "climate"
    assert 18 <= len(ds.holdings) <= 25 and len(ds.holdings) <= catalog.LIMITS["max_holdings"]
    sectors = {normalise_sector(h.sector) for h in ds.holdings}
    assert all(known for _, known in sectors)
    required = {"energy", "utilities", "materials", "industrials", "transportation", "technology",
                "financials", "health_care", "consumer", "real_estate"}
    assert required <= {s for s, _ in sectors}
    assert sum(h.market_value < 0 for h in ds.holdings) == 1
    miss12 = sum(h.scope1 is None or h.scope2 is None for h in ds.holdings) / len(ds.holdings)
    assert 0.25 <= miss12 <= 0.35
    assert sum(h.scope3 is None for h in ds.holdings) > len(ds.holdings) / 2
    assert {h.data_quality for h in ds.holdings} >= {1, 2, 3, 4, 5, None}
    assert sum(h.emissions_year is not None and h.emissions_year < ds.as_of.year - 2 for h in ds.holdings) == 1
    assert 2 <= sum(bool(h.controversy_flags) for h in ds.holdings) <= 4
    assert sum(bool(h.exclusion_flags) for h in ds.holdings) == 1


def test_sample_dataset_deterministic_and_seeded():
    assert sample_dataset().model_dump() == sample_dataset(0).model_dump()
    a, b = sample_dataset(0), sample_dataset(1)
    assert a.model_dump() != b.model_dump()
    assert [h.scope1 is None for h in a.holdings] == [h.scope1 is None for h in b.holdings]


def test_sample_data_quality_conforms_and_is_fair():
    out = DataQualityModel().run(sample_dataset(), {}, 0)
    assert check_output(SPEC, out) == []
    assert out.labels["quality"] == "fair"
    assert {f.check for f in out.findings} >= {"missing_scope12", "missing_scope3", "stale_emissions",
                                               "controversy", "exclusion_breach"}


def test_models_export():
    ms = models()
    assert [m.spec.model_id for m in ms] == ["q3.transition", "q3.data_quality"]
    assert all(m.spec is catalog.MODEL_SPECS[m.spec.model_id] for m in ms)
