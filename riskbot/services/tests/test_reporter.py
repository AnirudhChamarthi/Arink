"""Reporter tests: determinism, sections, and that every headline number verifies."""

import pytest

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.fakes import FIXED_NOW, FakeAssessor, fake_dataset
from riskbot.contract.types import (
    ExtraRun,
    GridSpec,
    QuestionId,
    QuestionPlan,
    ReviewDecision,
    RunRecord,
    RunResult,
    RunStatus,
    SignOff,
)
from riskbot.services.verifier import extract_numbers

from .helpers import make_error, make_result


def _run_result(q, variations, plan, synthetic=True):
    comp = services.comparator().compare(plan, variations)
    a = FakeAssessor().assess(q, fake_dataset(q), variations, comp)
    rec = RunRecord(run_id="run-0001", question=q, status=RunStatus.AWAITING_REVIEW, created_at=FIXED_NOW,
                    updated_at=FIXED_NOW, input_hash="ab" * 32, contract_version="2.0.0",
                    n_variations=len(variations), dataset_name="book 2026", synthetic=synthetic)
    return RunResult(run=rec, plan=plan, variations=variations, comparison=comp, assessment=a)


def _fake_run(q, fake_registry, synthetic=True):
    plan = catalog.DEFAULT_PLANS[q]
    res = services.executor(fake_registry).execute_many(services.planner().expand(plan, 11), fake_dataset(q))
    return _run_result(q, res, plan, synthetic)


def _hand_q2():
    plan = QuestionPlan(question=QuestionId.Q2, grid=GridSpec(model_id="q2.resilience",
                        dimensions={"rate_shock_bp": [100, 300], "run_speed": ["slow", "fast"]}),
                        extras=[ExtraRun(model_id="q2.reverse_stress", params={"target": "capital"}),
                                ExtraRun(model_id="q2.reverse_stress", params={"target": "liquidity",
                                                                              "rate_shock_bp": 300})])
    rows = [(100, "slow", 0.1234, 1.31, 52_345_678.9, "pass"), (100, "fast", 0.0912, 1.05, 61_000_000.0, "pass"),
            (300, "slow", 0.0801, 0.99, 70_500_000.0, "pass"), (300, "fast", 0.0467, 0.62, 91_234_567.0, "fail")]
    res = [make_result("q2.resilience", {"rate_shock_bp": s, "run_speed": sp},
                       {"capital_ratio_after": c, "lcr_after": l, "credit_loss": cl},
                       {"verdict": v, "binding_constraint": "none" if v == "pass" else "both"})
           for s, sp, c, l, cl, v in rows]
    res += [make_result("q2.reverse_stress", {"target": "capital"},
                        {"breakeven_deposit_outflow": 0.2345, "breakeven_rate_shock_bp": 412.5},
                        {"outflow_found": "yes", "rate_found": "yes"}, role="extra"),
            make_result("q2.reverse_stress", {"target": "liquidity", "rate_shock_bp": 300},
                        {"breakeven_deposit_outflow": 0.151}, {"outflow_found": "yes", "rate_found": "no"},
                        role="extra"),
            make_error("q2.resilience", {"rate_shock_bp": 600})]
    return _run_result(QuestionId.Q2, res, plan)


def _assert_headline_verifies(result, report):
    v = services.verifier()
    numbers = 0
    for sentence in report.headline:
        findings = v.verify_text("headline", sentence, result.variations)
        numbers += len(findings)
        assert all(f.matched for f in findings), (sentence, [f.message for f in findings if not f.matched])
    return numbers


@pytest.mark.parametrize("q", list(QuestionId))
def test_headline_numbers_verify_fake_models(q, fake_registry):
    result = _fake_run(q, fake_registry)
    report = services.reporter().build(result, None)
    assert _assert_headline_verifies(result, report) >= 4  # min and max of two metrics at least


def test_headline_numbers_verify_hand_built():
    result = _hand_q2()
    report = services.reporter().build(result, None)
    n = _assert_headline_verifies(result, report)
    text = " ".join(report.headline)
    assert "4.67%" in text and "12.34%" in text  # min / max of capital_ratio_after
    assert "23.45%" in text and "412 bp" in text  # found break-evens
    assert "target=capital" in text
    assert "Some variations failed" in text
    assert "flips with `rate_shock_bp`, `run_speed`" in text
    assert "mixed" in text
    assert n >= 7
    # the liquidity extra quotes a numeric parameter: its description is kept out of the headline
    assert "rate_shock_bp=300" not in text


def test_headline_never_cites_medians():
    result = _hand_q2()
    r = result.comparison.metric_ranges["capital_ratio_after"]
    text = " ".join(services.reporter().build(result, None).headline)
    assert f"{r.median * 100:.2f}%" not in text


def test_deterministic(fake_registry):
    a = services.reporter().build(_fake_run(QuestionId.Q1, fake_registry), None)
    b = services.reporter().build(_fake_run(QuestionId.Q1, fake_registry), None)
    assert a.markdown == b.markdown and a.headline == b.headline
    assert a == b


def test_markdown_sections_and_signoff():
    result = _hand_q2()
    so = SignOff(reviewer="Ana Analyst", decision=ReviewDecision.APPROVE, comment="Fine | ok", at=FIXED_NOW)
    report = services.reporter().build(result, so)
    md = report.markdown
    assert md.startswith("# " + catalog.QUESTIONS[QuestionId.Q2].title)
    order = ["## Run", "SYNTHETIC DATA", "## Headline", "## Metric ranges", "## Method spread", "## Sensitivity",
             "## Conclusion flips", "## Break-evens", "## Label counts", "## Qualitative assessment (Judgment)",
             "## Overrides", "## Sign-off", "## Variations"]
    positions = [md.index(s) for s in order]
    assert positions == sorted(positions)
    assert "Judgment, not calculation" in md
    assert "| `capital_ratio_after` | fraction | 4.67% |" in md
    assert "52,345,679" in md  # currency with thousands separators
    assert "412 bp" in md
    assert "Reviewer: Ana Analyst" in md and "Comment: Fine | ok" in md
    assert "error: RuntimeError: boom" in md
    assert report.signoff == so and report.comparison == result.comparison and report.run == result.run


def test_no_synthetic_banner_for_real_data(fake_registry):
    report = services.reporter().build(_fake_run(QuestionId.Q3, fake_registry, synthetic=False), None)
    assert "SYNTHETIC" not in report.markdown
    assert not any("synthetic" in s for s in report.headline)


def test_synthetic_sentence_in_headline(fake_registry):
    report = services.reporter().build(_fake_run(QuestionId.Q3, fake_registry), None)
    assert "synthetic" in report.headline[0]


def test_no_successful_variations():
    plan = catalog.DEFAULT_PLANS[QuestionId.Q1]
    result = _run_result(QuestionId.Q1, [make_error("q1.var", {})], plan)
    report = services.reporter().build(result, None)
    assert any("No grid variation completed" in s for s in report.headline)
    assert all(not extract_numbers(s) for s in report.headline)
    assert "No successful grid variations." in report.markdown
