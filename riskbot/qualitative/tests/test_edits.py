"""apply_edits: overrides, recomputed ratings, validation and immutability."""

from __future__ import annotations

import datetime as dt

import pytest

from riskbot.contract import rules
from riskbot.contract.errors import ValidationFailed
from riskbot.contract.types import ControlStrength, FactorEdit, FactorSource, Rating
from riskbot.qualitative import assessor

from ._scenarios import q1_low, q2_high

AT = dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.timezone.utc)


def _assessment(factory=q1_low):
    s = factory()
    return assessor().assess(s.question, s.dataset, s.results, s.comparison)


def test_edit_changes_ratings_and_logs_overrides():
    a = _assessment()
    before = a.model_dump_json()
    edited = assessor().apply_edits(a, [FactorEdit(factor_id="concentration", likelihood=5, impact=4,
                                                   control=ControlStrength.WEAK, reason="Known crowding")],
                                    "ana", AT)
    assert a.model_dump_json() == before  # input not mutated
    f = next(x for x in edited.factors if x.factor_id == "concentration")
    assert (f.likelihood, f.impact, f.control, f.source) == (5, 4, ControlStrength.WEAK, FactorSource.ANALYST)
    assert (f.inherent, f.residual) == rules.rate(5, 4, ControlStrength.WEAK) == (Rating.CRITICAL, Rating.CRITICAL)
    assert edited.overall == Rating.CRITICAL
    assert [(o.field, o.old, o.new) for o in edited.overrides] == [
        ("likelihood", 1, 5), ("impact", 3, 4), ("control", "adequate", "weak")]
    assert all(o.by == "ana" and o.reason == "Known crowding" and o.at == AT and o.factor_id == "concentration"
               for o in edited.overrides)
    assert [x.factor_id for x in edited.factors] == [x.factor_id for x in a.factors]


def test_unchanged_fields_are_not_logged_and_rationale_edit():
    a = _assessment()
    f0 = next(x for x in a.factors if x.factor_id == "history_length")
    edited = assessor().apply_edits(a, [FactorEdit(factor_id="history_length", likelihood=f0.likelihood,
                                                   rationale="Analyst view.", reason="wording")], "ana", AT)
    assert [(o.field, o.new) for o in edited.overrides] == [("rationale", "Analyst view.")]
    f = next(x for x in edited.factors if x.factor_id == "history_length")
    assert f.rationale == "Analyst view." and f.source == FactorSource.ANALYST


def test_noop_edit_keeps_source():
    a = _assessment()
    f0 = a.factors[0]
    edited = assessor().apply_edits(a, [FactorEdit(factor_id=f0.factor_id, impact=f0.impact, reason="ok")], "ana", AT)
    assert edited.overrides == [] and edited.factors[0].source == FactorSource.RULE


def test_edits_accumulate_overrides():
    a = _assessment(q2_high)
    e1 = assessor().apply_edits(a, [FactorEdit(factor_id="hedging", likelihood=3, reason="r1")], "x", AT)
    e2 = assessor().apply_edits(e1, [FactorEdit(factor_id="hedging", likelihood=2, reason="r2"),
                                     FactorEdit(factor_id="hedging", impact=1, reason="r3")], "y", AT)
    assert [(o.old, o.new, o.by) for o in e2.overrides] == [(5, 3, "x"), (3, 2, "y"), (4, 1, "y")]
    assert e1.overrides and len(e1.overrides) == 1  # earlier result untouched


def test_unknown_factor_rejected_atomically():
    a = _assessment()
    before = a.model_dump_json()
    with pytest.raises(ValidationFailed):
        assessor().apply_edits(a, [FactorEdit(factor_id="concentration", likelihood=5, reason="ok"),
                                   FactorEdit(factor_id="nope", likelihood=5, reason="bad")], "ana", AT)
    assert a.model_dump_json() == before


def test_bad_reviewer_or_naive_time_rejected():
    a = _assessment()
    e = [FactorEdit(factor_id="concentration", likelihood=5, reason="ok")]
    with pytest.raises(ValidationFailed):
        assessor().apply_edits(a, e, " ", AT)
    with pytest.raises(ValidationFailed):
        assessor().apply_edits(a, e, "ana", dt.datetime(2026, 11, 24, 12, 0))


def test_unassessed_factor_can_be_assessed_by_analyst():
    from ._scenarios import q1_missing

    a = _assessment(q1_missing)
    edited = assessor().apply_edits(a, [FactorEdit(factor_id="history_length", likelihood=2, impact=2,
                                                   control=ControlStrength.STRONG, reason="Checked by hand")],
                                    "ana", AT)
    f = next(x for x in edited.factors if x.factor_id == "history_length")
    assert f.source == FactorSource.ANALYST and f.residual == Rating.LOW
