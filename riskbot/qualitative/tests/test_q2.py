"""Q2 rubric: specific inputs drive specific ratings."""

from __future__ import annotations

from riskbot.contract.types import ControlStrength, FactorSource, QuestionId, Rating
from riskbot.qualitative import assessor

from ._builders import compare
from ._scenarios import q2_high, q2_low, q2_missing

Q2 = QuestionId.Q2


def _factors(s):
    a = assessor().assess(s.question, s.dataset, s.results, s.comparison)
    return {f.factor_id: f for f in a.factors}, a


def test_svb_like_balance_sheet_is_critical():
    f, a = _factors(q2_high())
    assert a.overall == Rating.CRITICAL
    u = f["uninsured_deposits"]
    assert (u.likelihood, u.impact, u.control) == (5, 5, ControlStrength.WEAK)
    assert "82.0%" in u.rationale and "5.0%" in u.rationale
    d = f["duration_gap"]
    assert (d.likelihood, d.impact, d.control) == (5, 5, ControlStrength.WEAK)
    assert "5.5 years" in d.rationale and "-35.0%" in d.rationale
    h = f["hedging"]
    assert h.likelihood == 5 and h.control == ControlStrength.WEAK
    assert any(e.ref == "governance.hedges_reduced_last_year" for e in h.evidence)


def test_htm_flip_raises_impact():
    f, _ = _factors(q2_high())
    htm = f["htm_reliance"]
    assert htm.likelihood == 5 and htm.impact == 5
    assert any(e.ref == "comparison.flips.htm_treatment" for e in htm.evidence)


def test_htm_flip_detected_from_results_without_comparator_flips():
    s = q2_high()
    s.comparison = compare(Q2, s.results)  # no flips supplied
    f, _ = _factors(s)
    assert f["htm_reliance"].impact == 5


def test_governance_cro_vacancy():
    f, _ = _factors(q2_high())
    g = f["risk_governance"]
    assert g.likelihood == 5 and g.control == ControlStrength.WEAK and g.residual == Rating.CRITICAL
    assert "vacant" in g.rationale
    assert {e.ref for e in g.evidence} >= {"governance.cro_vacancy_months", "governance.board_risk_expertise"}


def test_governance_absent_is_unassessed():
    f, _ = _factors(q2_missing())  # fake bank has no governance fields
    assert f["risk_governance"].source == FactorSource.UNASSESSED


def test_wholesale_and_breakeven():
    f, _ = _factors(q2_high())
    w = f["wholesale_dependence"]
    assert w.likelihood == 4 and w.impact == 4 and w.control == ControlStrength.WEAK
    assert "8.0%" in w.rationale
    low, _ = _factors(q2_low())
    assert low["wholesale_dependence"].likelihood == 1
    assert low["wholesale_dependence"].control == ControlStrength.STRONG


def test_credit_concentration_and_reconciliation():
    f, _ = _factors(q2_high())
    c = f["credit_concentration"]
    assert c.likelihood == 5 and c.control == ControlStrength.WEAK and "8.0%" in c.rationale


def test_low_risk_balance_sheet():
    f, _ = _factors(q2_low())
    for fid in ("uninsured_deposits", "deposit_concentration", "duration_gap", "hedging", "htm_reliance",
                "risk_governance"):
        assert f[fid].likelihood == 1, fid
        assert f[fid].residual == Rating.LOW, fid
    assert f["uninsured_deposits"].control == ControlStrength.STRONG
    assert f["risk_governance"].control == ControlStrength.STRONG
    assert f["hedging"].impact == 2  # small duration gap


def test_missing_data_quality_model():
    f, _ = _factors(q2_missing())
    for fid in ("uninsured_deposits", "deposit_concentration", "duration_gap", "hedging", "htm_reliance"):
        assert f[fid].source == FactorSource.UNASSESSED
        assert "failed" in f[fid].rationale
    assert f["wholesale_dependence"].source == FactorSource.RULE
    assert f["credit_concentration"].source == FactorSource.RULE
