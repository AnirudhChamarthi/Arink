"""catalog.LIMITS enforcement before the service is called, and trace Markdown rendering."""

from __future__ import annotations

import datetime as dt

from riskbot.contract import catalog
from riskbot.contract.fakes import fake_dataset
from riskbot.contract.types import (
    BsAsset,
    ClimateHolding,
    GridSpec,
    MarketPosition,
    QuestionId,
    QuestionPlan,
    Trace,
    TraceStep,
    Unit,
)
from riskbot.mcp_server import limits
from riskbot.mcp_server.rendering import format_number, render_table, render_trace
from riskbot.mcp_server.tests.helpers import call, error_text

Q1, Q2, Q3 = QuestionId.Q1, QuestionId.Q2, QuestionId.Q3
L = catalog.LIMITS


def _too_many_positions() -> dict:
    ds = fake_dataset(Q1)
    cash = [MarketPosition(ticker=f"CASH{i}", asset_class="cash", quantity=1, price=1.0)
            for i in range(L["max_positions"])]
    return ds.model_copy(update={"positions": ds.positions + cash}).model_dump(mode="json")


def _too_long_history() -> dict:
    n = L["max_history_days"] + 1
    dates = [dt.date(2000, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    ds = fake_dataset(Q1)
    return ds.model_copy(update={"dates": dates, "as_of": dates[-1],
                                 "returns": {"AAA": [0.0] * n, "BBB": [0.0] * n}}).model_dump(mode="json")


def _too_big_balance_sheet() -> dict:
    ds = fake_dataset(Q2)
    extra = [BsAsset(id=f"o{i}", kind="other", book_value=1, market_value=1, coupon_rate=0.0, maturity_years=0,
                     repricing_years=0) for i in range(L["max_balance_sheet_items"])]
    return ds.model_copy(update={"assets": ds.assets + extra}).model_dump(mode="json")


def _too_many_holdings() -> dict:
    ds = fake_dataset(Q3)
    h = ClimateHolding(issuer="X", sector="energy", market_value=1, evic=1, revenue=1)
    return ds.model_copy(update={"holdings": [h] * (L["max_holdings"] + 1)}).model_dump(mode="json")


def _assert_limit(result, name: str) -> None:
    text = error_text(result)
    assert text.startswith("limit_exceeded: ") and name in text, text


def test_dataset_limits_on_every_dataset_tool(server, service):
    cases = [(Q1, _too_many_positions(), "max_positions"), (Q1, _too_long_history(), "max_history_days"),
             (Q2, _too_big_balance_sheet(), "max_balance_sheet_items"), (Q3, _too_many_holdings(), "max_holdings")]
    model_for = {Q1: "q1.var", Q2: "q2.resilience", Q3: "q3.transition"}
    for question, ds, limit in cases:
        _assert_limit(call(server, "validate_dataset", {"dataset": ds}), limit)
        _assert_limit(call(server, "calculate", {"model_id": model_for[question], "dataset": ds}), limit)
        _assert_limit(call(server, "start_run", {"question": question.value, "dataset": ds}), limit)
    assert service.calls == []  # the service was never reached


def test_plan_variation_limit(server, service):
    plan = QuestionPlan(question=Q3, grid=GridSpec(model_id="q3.transition", dimensions={
        "horizon_years": list(range(1, 31)), "n_sims": list(range(100, 3500, 100))}))
    assert limits.plan_size(plan) > L["max_variations"]
    result = call(server, "start_run", {"question": "q3_transition", "dataset": fake_dataset(Q3).model_dump(mode="json"),
                                        "plan": plan.model_dump(mode="json")})
    _assert_limit(result, "max_variations")
    assert service.calls == []


def test_limits_at_boundary_pass():
    limits.check_dataset(fake_dataset(Q1))
    limits.check_plan(catalog.DEFAULT_PLANS[Q2])
    assert limits.plan_size(catalog.DEFAULT_PLANS[Q2]) == 4 * 2 * 2 * 2 + 3


# ------------------------------------------------------------------------------ rendering


def _trace() -> Trace:
    return Trace(
        trace_id="q1.var-abcdefabcdef", model_id="q1.var", title="Portfolio VaR",
        assumptions=["Returns are i.i.d.", "Square-root-of-time scaling."],
        inputs={"params": {"method": "normal"}, "n_positions": 2},
        steps=[
            TraceStep(id="sigma", title="Portfolio volatility", formula=r"\sigma_p=\sqrt{w^\top\Sigma w}",
                      substitution=r"\sqrt{0.0004}", value=0.02, unit=Unit.FRACTION),
            TraceStep(id="weights", title="Weights", formula=r"w_i = MV_i / \sum|MV|", substitution="see table",
                      table=[{"ticker": "AAA", "weight": 0.5}, {"ticker": "B|B", "weight": -0.5, "note": None}],
                      note="Signed weights."),
            TraceStep(id="var", title="VaR", formula=r"z_c\sigma_p\sqrt{h}", substitution=r"2.326 \times 0.02",
                      value=0.1 + 0.2, unit=Unit.FRACTION_OF_GROSS),
        ],
        result={"var": 0.3}, input_hash="f" * 64, warnings=["Window shorter than requested."],
    )


def test_render_trace_structure():
    md = render_trace(_trace())
    assert md.startswith("# Portfolio VaR\n")
    assert "- Returns are i.i.d." in md
    assert "### 1. Portfolio volatility" in md and "### 3. VaR" in md
    assert "$$\n\\sigma_p=\\sqrt{w^\\top\\Sigma w}\n$$" in md
    assert "**Value:** 0.02 fraction" in md
    assert "**Value:** 0.3 fraction_of_gross" in md  # no float noise
    assert "| ticker | weight | note |" in md and r"| B\|B | -0.5 |  |" in md
    assert "_Note:_ Signed weights." in md
    assert "- Window shorter than requested." in md
    assert "f" * 64 in md


def test_render_trace_is_deterministic():
    assert render_trace(_trace()) == render_trace(_trace())


def test_format_number_and_empty_table():
    assert format_number(None) == "" and format_number(3) == "3" and format_number(True) == "true"
    assert format_number(1234567.891) == "1234567.891"
    assert render_table([]) == "_(empty table)_"
