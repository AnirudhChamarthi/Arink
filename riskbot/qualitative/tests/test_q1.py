"""Q1 rubric: specific inputs drive specific ratings."""

from __future__ import annotations

from riskbot.contract.types import Comparison, ControlStrength, FactorSource, QuestionId, Rating
from riskbot.qualitative import assessor

from ._builders import compare
from ._scenarios import Scenario, q1_high, q1_low, q1_missing, q1_results

Q1 = QuestionId.Q1


def _factors(s):
    a = assessor().assess(s.question, s.dataset, s.results, s.comparison)
    return {f.factor_id: f for f in a.factors}, a


def test_low_risk_book_is_low_overall():
    f, a = _factors(q1_low())
    assert a.overall == Rating.LOW
    assert f["method_spread"].likelihood == 1 and f["method_spread"].control == ControlStrength.STRONG
    assert f["backtest_performance"].likelihood == 1
    assert f["history_length"].likelihood == 1
    assert f["data_quality"].likelihood == 1
    assert f["concentration"].likelihood == 1
    assert f["short_exposure"].likelihood == 1 and "no short" in f["short_exposure"].rationale


def test_method_spread_above_two_is_high_likelihood():
    f, _ = _factors(q1_high())
    ms = f["method_spread"]
    assert ms.likelihood == 4 and ms.impact == 4  # spread 2.6 > 2
    assert ms.inherent == Rating.CRITICAL and ms.residual == Rating.MEDIUM  # six methods -> strong control
    assert "2.0%" in ms.rationale and "5.2%" in ms.rationale
    assert any(e.ref == "comparison.method_spread.var" for e in ms.evidence)


def test_method_spread_falls_back_to_results_without_comparator_spread():
    s = q1_high()
    s.comparison = Comparison(question=Q1, metric_ranges={})
    f, _ = _factors(s)
    assert f["method_spread"].source == FactorSource.RULE and f["method_spread"].likelihood == 4


def test_failing_backtests_and_red_zone():
    f, _ = _factors(q1_high())
    bt = f["backtest_performance"]
    assert bt.likelihood == 4 and bt.inherent == Rating.CRITICAL
    assert "red zone" in bt.rationale and "14" in bt.rationale


def test_backtest_without_verdicts_is_unassessed():
    res = q1_results({"normal": 0.03, "evt": 0.04}, verdicts={"normal": "n/a", "evt": "n/a"})
    f, _ = _factors(Scenario(Q1, q1_low().dataset, res, compare(Q1, res)))
    assert f["backtest_performance"].source == FactorSource.UNASSESSED


def test_short_history_and_window_sensitivity():
    f, _ = _factors(q1_high())
    h = f["history_length"]
    assert h.likelihood == 5 and h.control == ControlStrength.WEAK and "300" in h.rationale


def test_poor_data_with_errors():
    f, _ = _factors(q1_high())
    dq = f["data_quality"]
    assert dq.likelihood == 5 and dq.control == ControlStrength.WEAK
    assert {e.ref for e in dq.evidence if e.kind == "finding"} == {"missing_returns", "stale_price"}


def test_concentrated_book_with_short():
    f, _ = _factors(q1_high())  # fake book: AAA is ~86% of gross, BBB short ~14%
    assert f["concentration"].likelihood == 5
    assert f["short_exposure"].likelihood == 3
    assert "one short position" in f["short_exposure"].rationale


def test_normality_reliance_with_failing_normal_backtest():
    f, _ = _factors(q1_high())
    n = f["normality_reliance"]
    assert n.likelihood == 5 and n.control == ControlStrength.WEAK and n.residual == Rating.CRITICAL
    low, _ = _factors(q1_low())
    assert low["normality_reliance"].likelihood == 2  # 3.3% / 3.0% = 1.1
    assert low["normality_reliance"].control == ControlStrength.ADEQUATE


def test_missing_inputs():
    f, _ = _factors(q1_missing())
    for fid in ("method_spread", "backtest_performance", "history_length", "data_quality", "normality_reliance"):
        assert f[fid].source == FactorSource.UNASSESSED
        assert (f[fid].likelihood, f[fid].impact, f[fid].control) == (3, 3, ControlStrength.ADEQUATE)
    assert "Market data quality" in f["history_length"].rationale
    # dataset-only factors still work when every model failed
    assert f["concentration"].source == FactorSource.RULE
