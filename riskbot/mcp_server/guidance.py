"""Text the server gives to language models: server instructions and prompt templates.

The rules here encode the contract's principles for an LLM client:

* numbers come only from tool results (CONTRACT.md principle 6: language models never produce numbers);
* every quoted number is cited with its ``trace_id`` (and step), so a reader can open the working;
* synthetic datasets are described as synthetic;
* judgment (the qualitative assessment) is labelled as judgment;
* review and sign-off are human-only and are deliberately not exposed as tools.
"""

from __future__ import annotations

from riskbot.contract import catalog
from riskbot.contract.types import QuestionId

__all__ = ["SERVER_INSTRUCTIONS", "PROMPTS", "render_prompt"]

SERVER_INSTRUCTIONS = """\
Riskbot runs verifiable risk analyses: market tail risk (q1_market), balance-sheet resilience to a rate
shock plus deposit run (q2_balance_sheet) and low-carbon transition risk (q3_transition). Each analysis
runs a grid of model variations, compares them and pre-fills a qualitative rubric.

Rules for reporting results:
1. Quote numbers ONLY from tool results or resources. Never estimate, compute, round into new figures or
   invent numbers yourself.
2. Every number you quote has a trace_id (Metric.trace_id / trace_step, BreakEven.trace_id). Cite it next
   to the number, e.g. "VaR 4.1% of gross (trace q1.var-1a2b3c4d5e6f, step var)". Use get_trace or the
   resource riskbot://traces/{trace_id} to show the working.
3. Datasets with synthetic=true (all built-in samples) are synthetic: say so whenever you describe the data
   or the results based on it.
4. The qualitative assessment is labelled "judgment": present it as judgment, not as calculation.
5. Mention data-quality findings and failed variations; do not hide them.

Typical flow: list_questions -> get_sample_dataset (or the user's dataset) -> validate_dataset ->
optional calculate for a single model -> start_run (waits for the result by default) -> run_status ->
run_result -> get_trace for cited numbers -> get_report.

Review and sign-off are human-only by design: there is no review, approve or sign-off tool. When a run is
awaiting_review, tell the user that a human reviewer must approve or reject it in the Riskbot web UI or
REST API. Errors are returned as tool errors of the form "<code>: <message>" (not_found,
validation_failed, conflict, limit_exceeded, internal)."""


# name -> (question, title, focus of the analysis)
PROMPTS: dict[str, tuple[QuestionId, str, str]] = {
    "assess_market_risk": (
        QuestionId.Q1,
        "Assess market tail risk",
        "Report the range of VaR and expected shortfall across methods and windows (metric_ranges), the method "
        "spread, which variations fail the backtest (backtest_verdict flips) and the data-quality findings. "
        "Explain how far the headline VaR can be trusted given the spread and backtests.",
    ),
    "assess_balance_sheet": (
        QuestionId.Q2,
        "Assess balance-sheet resilience",
        "Report which combinations of rate shock, run speed, loss severity and HTM treatment pass or fail "
        "(verdict flips and label_counts), the binding constraint, the capital and LCR ranges and the reverse "
        "stress break-evens (break_evens).",
    ),
    "assess_transition_risk": (
        QuestionId.Q3,
        "Assess transition risk",
        "Report the loss range across scenarios, price paths and missing-data treatments, the spread caused by "
        "the missing-data treatment, WACI / financed emissions, the share of estimated emissions and the "
        "climate data-quality findings.",
    ),
}


def render_prompt(name: str, dataset_hint: str | None = None) -> str:
    """Build the guidance message for one of ``PROMPTS``.

    ``dataset_hint`` is a free-text description of the data the user wants analysed (for example
    "my equity book in positions.json"); without it the model is told to use the synthetic sample.
    """
    question, title, focus = PROMPTS[name]
    info = catalog.QUESTIONS[question]
    hint = (dataset_hint or "").strip()
    if hint:
        data_step = (
            f"The user describes the data as: \"{hint}\". Build a `{info.dataset_kind.value}` dataset from it "
            f"(kind=\"{info.dataset_kind.value}\"; set synthetic=false only if it is real data). If anything is "
            f"unclear, ask before guessing. You may call get_sample_dataset(question=\"{question.value}\") to see "
            "the expected shape."
        )
    else:
        data_step = (
            f"No dataset was described, so call get_sample_dataset(question=\"{question.value}\") and use it. "
            "It is SYNTHETIC: say so in your answer."
        )
    return f"""\
{title}: {info.title}

Steps:
1. {data_step}
2. Call validate_dataset(dataset) and summarise the data-quality findings (severity, field, message).
3. Call start_run(question="{question.value}", dataset=...) (omit plan to use the default plan; wait=true
   is the default and returns once the run is awaiting_review or failed). If the status is failed, report
   the error and stop.
4. Call run_result(run_id). {focus}
5. For every number you quote, cite its trace_id (and step); call get_trace(trace_id) for the one or two
   most important numbers and show the formula and substitution.
6. Call get_report(run_id) and use its headline sentences as the summary.

Reporting rules:
- Quote numbers only from tool results; never compute or estimate new numbers yourself.
- Every number has a trace_id: cite it.
- If the dataset is synthetic (synthetic=true), state clearly that the data and results are synthetic.
- Present the qualitative assessment as judgment, with its evidence.
- The run ends in awaiting_review: a human reviewer must approve or reject it in the Riskbot UI or REST
  API. You cannot and must not sign it off."""
