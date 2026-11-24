"""Verifier tests: metric/trace re-check and number matching in free text."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import riskbot.services as services
from riskbot.contract.types import Unit
from riskbot.services.formatting import format_value
from riskbot.services.verifier import extract_numbers

from .helpers import make_error, make_result


@pytest.fixture(scope="module")
def results():
    return [
        make_result("q1.var", {}, {"var": 0.3118, "var_amount": 1234567.0, "kupiec_p": 0.0423,
                                   "backtest_exceptions": 7.0, "gross_exposure": 2_500_000_000.0}),
        make_result("q2.reverse_stress", {}, {"breakeven_rate_shock_bp": 187.5, "breakeven_deposit_outflow": 0.0125},
                    role="extra"),
        make_result("q2.resilience", {}, {"delta_eve": -1.2e9, "lcr_after": 1.234}),
        make_error("q1.var", {"method": "evt"}),
    ]


V = services.verifier()


def _one(text, results):
    f = V.verify_text("loc", text, results)
    assert len(f) == 1, f
    return f[0]


@pytest.mark.parametrize("text", [
    "VaR is 31.2% of gross.", "VaR is 31.18%.", "VaR is 31%.", "VaR 0.3118", "VaR 0.31",
    "VaR amount $1,234,567", "VaR amount USD 1.23m", "VaR amount 1,235k", "VaR amount US$1.2m",
    "gross exposure $2.5bn", "gross exposure 2.5 billion", "gross 2,500m",
    "p-value 0.042", "p-value 4.2%", "seven exceptions: 7",
    "break-even shock 188 bp", "break-even 187.5bps", "break-even 1.875%",
    "outflow 1.25%", "outflow 125bp", "outflow 0.0125",
    "EVE falls by 1.2bn", "EVE change -$1.2bn", "EVE change -1,200,000,000",
    "LCR 1.23", "LCR 1.23x", "LCR 123%",
])
def test_positive_matches(text, results):
    f = _one(text, results)
    assert f.matched, f.message
    assert "matches" in f.message and "variation" in f.message


@pytest.mark.parametrize("text", [
    "VaR is 31.3%.",          # off by more than half a unit of the last digit (31.18 -> 31.3)
    "VaR is 32%.",
    "VaR 0.312",              # |0.312 - 0.3118| = 0.0002 <= 0.0005: matches
])
def test_rounding_boundaries(text, results):
    f = _one(text, results)
    assert f.matched == (text == "VaR 0.312")


@pytest.mark.parametrize("text", [
    "VaR is 12.5%.", "$999", "EVE change +1.2bn", "loss of 42 bp", "LCR 2.5", "amount 1.3m",
    "VaR amount $0.3118",     # currency symbol restricts candidates to currency metrics
    "exceptions: 8",
])
def test_negative_matches(text, results):
    f = _one(text, results)
    assert not f.matched
    assert f.value is not None and "does not match" in f.message


def test_failed_variations_are_not_candidates():
    res = [make_error("q1.var", {})]
    assert not _one("VaR 0.05", res).matched


@pytest.mark.parametrize("text", [
    "Likelihood 3, impact 4, rated 5 of 5.",
    "Data from 2025 and 1999 only.",
    "Model q1.var, variation v1a2b3c4d5, run run-0001, trace q1.var-0a1b2c3d4e5f, also 0a1b2c3d.",
    "CET1 ratio and loss_p05 and q2.reverse_stress and the 5th percentile.",
    "version 1.2.3",
])
def test_ignored_numbers(text, results):
    assert V.verify_text("loc", text, results) == []


def test_units_on_small_integers_are_not_ignored(results):
    texts = ["3%", "4 bp", "$5", "2.0", "-3"]
    for t in texts:
        assert len(V.verify_text("loc", t, results)) == 1, t


def test_ranges_and_values_reported(results):
    f = V.verify_text("factor:x/rationale", "VaR between 31.2%-31.18% and $1.2m.", results)
    assert [x.text for x in f] == ["31.2%", "31.18%", "$1.2m"]
    assert [x.value for x in f] == [31.2, 31.18, 1.2]
    assert all(x.matched and x.location == "factor:x/rationale" for x in f)


def test_explicit_sign_must_match(results):
    assert _one("delta EVE -1.2bn", results).matched
    assert not _one("delta EVE +1.2bn", results).matched
    assert not _one("VaR -31.2%", results).matched


def test_extract_numbers_shapes():
    toks = extract_numbers("USD 1.2bn, -$5m, 25bp, 1,234.5 and .5 and 10k")
    assert [(t.value, t.kind, t.scale, t.currency, t.decimals) for t in toks] == [
        (1.2, "scale", 1e9, True, 1), (-5.0, "scale", 1e6, True, 0), (25.0, "bp", 1.0, False, 0),
        (1234.5, "plain", 1.0, False, 1), (0.5, "plain", 1.0, False, 1), (10.0, "scale", 1e3, False, 0)]


# -- check_outputs ----------------------------------------------------------------------------

def test_check_outputs_clean(results):
    assert V.check_outputs(results) == []


def test_check_outputs_mismatch_and_unlinked(results):
    r = results[0]
    metrics = dict(r.output.metrics)
    metrics["var"] = metrics["var"].model_copy(update={"value": 0.5})
    metrics["es"] = metrics["var"].model_copy(update={"trace_id": None})
    metrics["var_amount"] = metrics["var_amount"].model_copy(update={"trace_step": "nope"})
    bad = r.model_copy(update={"output": r.output.model_copy(update={"metrics": metrics})})
    findings = V.check_outputs([bad, results[1]])
    assert {f.location.rsplit(":", 1)[1] for f in findings} == {"var", "es", "var_amount"}
    assert not any(f.matched for f in findings)
    assert any("differs from trace step" in f.message for f in findings)
    assert any("not linked" in f.message for f in findings)
    assert any("missing trace step" in f.message for f in findings)


# -- property: every formatted value verifies against itself ----------------------------------

UNITS = [Unit.FRACTION, Unit.FRACTION_OF_GROSS, Unit.PROBABILITY, Unit.CURRENCY, Unit.BASIS_POINTS, Unit.RATIO]


@settings(max_examples=150, deadline=None)
@given(st.floats(min_value=-1e10, max_value=1e10, allow_nan=False), st.sampled_from(UNITS))
def test_formatted_values_verify(value, unit):
    key = {Unit.FRACTION: "breakeven_deposit_outflow", Unit.BASIS_POINTS: "breakeven_rate_shock_bp"}
    if unit in key:
        r = make_result("q2.reverse_stress", {}, {key[unit]: value})
    else:
        k = {Unit.FRACTION_OF_GROSS: "var", Unit.PROBABILITY: "kupiec_p", Unit.CURRENCY: "var_amount",
             Unit.RATIO: "var"}[unit]
        r = make_result("q1.var", {}, {k: value}, units={k: unit})
    text = f"The value is {format_value(value, unit)}."
    findings = V.verify_text("prop", text, [r])
    assert findings and all(f.matched for f in findings), (text, findings)
