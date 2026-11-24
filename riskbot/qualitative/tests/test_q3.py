"""Q3 rubric: specific inputs drive specific ratings."""

from __future__ import annotations

from riskbot.contract.types import ControlStrength, FactorSource, QuestionId, Rating
from riskbot.qualitative import assessor

from ._scenarios import q3_high, q3_low, q3_missing

Q3 = QuestionId.Q3


def _factors(s):
    a = assessor().assess(s.question, s.dataset, s.results, s.comparison)
    return {f.factor_id: f for f in a.factors}, a


def test_clean_portfolio_is_low():
    f, a = _factors(q3_low())
    assert a.overall == Rating.LOW
    assert all(x.residual == Rating.LOW for x in f.values())
    assert f["emissions_coverage"].control == ControlStrength.STRONG
    assert f["estimated_emissions"].control == ControlStrength.STRONG and "1.40" in f["estimated_emissions"].rationale


def test_poor_data_portfolio():
    f, a = _factors(q3_high())
    assert a.overall == Rating.CRITICAL
    cov = f["emissions_coverage"]
    assert cov.likelihood == 5 and cov.control == ControlStrength.WEAK and "32.0%" in cov.rationale
    est = f["estimated_emissions"]
    assert est.likelihood == 5 and est.control == ControlStrength.WEAK and "68.0%" in est.rationale
    assert f["scope3_coverage"].likelihood == 5 and f["scope3_coverage"].impact == 4
    assert f["stale_data"].likelihood == 5
    assert any(e.kind == "finding" and e.ref == "stale_emissions" for e in f["stale_data"].evidence)
    assert f["controversies"].likelihood == 5 and "Coalco" in f["controversies"].rationale


def test_exclusion_breach_counts_longs_only():
    f, _ = _factors(q3_high())
    ex = f["exclusion_breaches"]
    assert ex.likelihood == 5 and ex.control == ControlStrength.WEAK and ex.residual == Rating.CRITICAL
    assert "Coalco" in ex.rationale and "Shortco" not in ex.rationale  # short positions are not breaches
    assert [e.ref for e in ex.evidence] == ["holdings[2].exclusion_flags"]
    low, _ = _factors(q3_low())
    assert low["exclusion_breaches"].likelihood == 1


def test_high_emitting_concentration():
    f, _ = _factors(q3_high())  # energy 1000 + materials 800 of 3800 long
    assert f["high_emitting_concentration"].likelihood == 5
    low, _ = _factors(q3_low())  # one utility, about a seventeenth of long value
    assert low["high_emitting_concentration"].likelihood == 1


def test_scenario_dispersion():
    f, _ = _factors(q3_high())
    sd = f["scenario_dispersion"]
    assert sd.likelihood == 5 and sd.impact == 4  # 12.0% / 0.8% = 15x, worst 12% loss
    assert "0.8%" in sd.rationale and "12.0%" in sd.rationale
    low, _ = _factors(q3_low())
    assert low["scenario_dispersion"].likelihood == 1 and low["scenario_dispersion"].impact == 1


def test_missing_models():
    f, _ = _factors(q3_missing())
    for fid in ("emissions_coverage", "estimated_emissions", "scope3_coverage", "stale_data", "controversies",
                "scenario_dispersion"):
        assert f[fid].source == FactorSource.UNASSESSED, fid
    assert f["exclusion_breaches"].source == FactorSource.RULE
    assert f["high_emitting_concentration"].source == FactorSource.RULE
