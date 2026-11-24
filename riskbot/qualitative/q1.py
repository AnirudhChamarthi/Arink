"""Q1 rubric: how far should we trust the VaR number? (market tail risk)

Every rule reads only ``Inputs`` (dataset, variation outputs, comparison) and returns an ``Outcome``
or raises ``MissingInput``. Thresholds live in the ``params`` of each ``FactorDef`` row.
"""

from __future__ import annotations

from riskbot.contract.types import ControlStrength as C
from riskbot.contract.types import MarketDataset

from ._base import FactorDef, Outcome
from ._inputs import (
    Inputs,
    MetricRef,
    MissingInput,
    band_down,
    band_up,
    by_param,
    comparison_evidence,
    count_words,
    plural,
    field_evidence,
    finding_evidence,
    label_evidence,
    lower_median,
    safe_name,
    share_words,
)

VAR, DQ = "q1.var", "q1.data_quality"


def _method_medians(inp: Inputs) -> dict[str, MetricRef]:
    """Lower-median VaR per method over successful grid variations (positive values only)."""
    groups = by_param([r for r in inp.grid_refs(VAR, "var") if r.value > 0], "method")
    return {m: lower_median(refs) for m, refs in groups.items()}


def method_spread(inp: Inputs, fd: FactorDef) -> Outcome:
    medians = _method_medians(inp)
    ev = []
    spread = inp.comparison.method_spread.get("var")
    if spread is not None:
        ev.append(comparison_evidence("method_spread.var", "Max/min of per-method median VaR (comparator)."))
    elif len(medians) >= 2:
        spread = max(r.value for r in medians.values()) / min(r.value for r in medians.values())
    if spread is None or len(medians) < 2:
        raise MissingInput("VaR results for at least two methods (comparison.method_spread['var'] or grid outputs)")
    lo = min(medians.items(), key=lambda kv: kv[1].value)
    hi = max(medians.items(), key=lambda kv: kv[1].value)
    likelihood = band_up(spread, fd.params["spread_cuts"])
    n = len(medians)
    control = C.STRONG if n >= fd.params["strong_methods"] else C.ADEQUATE if n >= fd.params["adequate_methods"] else C.WEAK
    verdict = {1: "methods broadly agree", 2: "methods broadly agree", 3: "the choice of method matters",
               4: "the choice of method alone changes the risk number by a factor of two or more",
               5: "the choice of method alone changes the risk number by a factor of three or more"}[likelihood]
    rationale = (f"Median-ranked VaR per method ranges from {lo[1].text} ({lo[0]}) to {hi[1].text} ({hi[0]}) "
                 f"across {count_words(n)} methods, so {verdict}.")
    ev += lo[1].evidence(f"Median-ranked VaR, method {lo[0]}") + hi[1].evidence(f"Median-ranked VaR, method {hi[0]}")
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def backtest_performance(inp: Inputs, fd: FactorDef) -> Outcome:
    ev = []
    verdicts = inp.comparison.label_counts.get("backtest_verdict")
    zones = inp.comparison.label_counts.get("basel_zone")
    grid = inp.grid(VAR)
    if verdicts is not None:
        ev.append(comparison_evidence("label_counts.backtest_verdict", f"Backtest verdict counts: {verdicts}."))
    else:  # same definition as the comparator: counts over successful grid variations
        verdicts = {}
        for r in grid:
            v = r.output.labels.get("backtest_verdict") if r.output else None
            if v:
                verdicts[v] = verdicts.get(v, 0) + 1
        ev += [label_evidence(r, "backtest_verdict") for r in grid if r.output and "backtest_verdict" in r.output.labels]
    if zones is not None:
        ev.append(comparison_evidence("label_counts.basel_zone", f"Basel zone counts: {zones}."))
    else:
        zones = {}
        for r in grid:
            z = r.output.labels.get("basel_zone") if r.output else None
            if z:
                zones[z] = zones.get(z, 0) + 1
    n_pass, n_fail = verdicts.get("pass", 0), verdicts.get("fail", 0)
    if n_pass + n_fail == 0:
        raise MissingInput("backtest verdicts (backtest disabled, not applicable, or no successful VaR variation)", ev)
    fail_share = n_fail / (n_pass + n_fail)
    likelihood = band_up(fail_share, fd.params["fail_share_cuts"])
    red, yellow = zones.get("red", 0), zones.get("yellow", 0)
    if red:
        likelihood = max(likelihood, fd.params["red_floor"])
    elif yellow:
        likelihood = max(likelihood, fd.params["yellow_floor"])
    phrase = ("all backtested variations pass the Kupiec and Christoffersen tests" if n_fail == 0 else
              f"{share_words(fail_share)} of backtested variations fail the Kupiec or Christoffersen test")
    zone = (", and at least one variation is in the Basel red zone" if red else
            ", and at least one variation is in the Basel yellow zone" if yellow else "")
    worst = max(inp.grid_refs(VAR, "backtest_exceptions"), key=lambda r: r.value, default=None)
    extra = ""
    if worst is not None:
        extra = f" The worst variation ({worst.params.get('method', 'unknown method')}) had {worst.text} exceptions."
        ev += worst.evidence("Most backtest exceptions in any variation")
    rationale = phrase[0].upper() + phrase[1:] + zone + "." + extra
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def history_length(inp: Inputs, fd: FactorDef) -> Outcome:
    days = inp.require(DQ, "history_days")
    likelihood = band_down(days.value, fd.params["days_cuts"])
    ev = days.evidence("Length of the return history")
    window_note = ""
    for row in inp.comparison.sensitivity:
        if row.dimension == "window_days" and row.metric == "var" and row.medians:
            lo = min(row.medians.values())
            if lo > 0 and row.effect / lo >= fd.params["window_effect"]:
                window_note = ", and VaR changes materially between the short and the long estimation window"
                ev.append(comparison_evidence("sensitivity.window_days.var", "Effect of the window on median VaR."))
                likelihood = min(5, likelihood + 1)
            break
    short = days.value < fd.params["long_window"]
    control = C.WEAK if short else C.ADEQUATE
    desc = ("too short to fill the longest estimation window" if short else
            "long enough to fill every estimation window")
    rationale = f"The return history covers {days.text} trading days, {desc}{window_note}."
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def data_quality(inp: Inputs, fd: FactorDef) -> Outcome:
    res = inp.first(DQ)
    if res is None or res.output is None or "quality" not in res.output.labels:
        raise MissingInput(f"the data-quality label because {inp.why_missing(DQ)}")
    quality = res.output.labels["quality"]
    likelihood = fd.params["quality_likelihood"][quality]
    findings = inp.findings()
    sev = {f.severity.value for f in findings}
    if "error" in sev:
        likelihood = min(5, likelihood + 1)
    elif "warning" in sev:
        likelihood = max(likelihood, 2)
    ev = [label_evidence(res, "quality")]
    parts = []
    for key, desc in (("missing_share", "of return values missing"), ("stale_series", "stale series"),
                      ("outlier_count", "outlier returns")):
        ref = inp.ref(res, key)
        if ref is not None:
            parts.append(f"{ref.text} {desc}")
            ev += ref.evidence(key)
    seen = set()
    for f in findings:
        if f.check not in seen:
            seen.add(f.check)
            ev.append(finding_evidence(f))
    detail = (" (" + ", ".join(parts) + ")") if parts else ""
    tail = (", including errors" if "error" in sev else ", with warnings" if "warning" in sev else
            "" if findings else " and no findings were raised")
    control = C.WEAK if quality == "poor" else C.ADEQUATE
    rationale = f"The data-quality check rates the market data {quality}{detail}{tail}."
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


def _weights(ds: MarketDataset) -> tuple[float, list[tuple[int, float]]]:
    mv = [(i, p.quantity * p.price) for i, p in enumerate(ds.positions)]
    gross = sum(abs(v) for _, v in mv)
    return gross, mv


def _market(inp: Inputs) -> MarketDataset:
    if not isinstance(inp.dataset, MarketDataset):
        raise MissingInput("a market dataset")
    return inp.dataset


def concentration(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _market(inp)
    gross, mv = _weights(ds)
    risky = [(i, v) for i, v in mv if ds.positions[i].asset_class != "cash"]
    if gross <= 0 or not risky:
        raise MissingInput("non-cash positions with non-zero gross exposure")
    i, v = max(risky, key=lambda kv: abs(kv[1]))
    w = abs(v) / gross
    likelihood = band_up(w, fd.params["weight_cuts"])
    hhi = sum((abs(x) / gross) ** 2 for _, x in risky)
    n_eff = 1 / hhi if hhi > 0 else 0.0
    p = ds.positions[i]
    name = safe_name(p.ticker, "the largest position")
    diversified = ("the book is well diversified" if n_eff >= fd.params["n_eff_diversified"] else
                   "the book behaves like a handful of positions")
    tail = (", so a single-name shock can dominate the tail" if likelihood >= 3 else
            ", so no single name dominates the tail")
    rationale = f"The largest non-cash position ({name}) is {share_words(w)} of gross exposure and {diversified}{tail}."
    ev = [field_evidence(f"positions[{i}].quantity", f"Quantity of {p.ticker}."),
          field_evidence(f"positions[{i}].price", f"Price of {p.ticker}; weight = |MV| / gross exposure.")]
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def short_exposure(inp: Inputs, fd: FactorDef) -> Outcome:
    ds = _market(inp)
    gross, mv = _weights(ds)
    if gross <= 0:
        raise MissingInput("positions with non-zero gross exposure")
    shorts = [(i, v) for i, v in mv if v < 0]
    share = sum(-v for _, v in shorts) / gross
    likelihood = band_up(share, fd.params["short_share_cuts"])
    if not shorts:
        rationale = "The book has no short positions, so there is no exposure to squeezes or borrow recalls."
        ev = [field_evidence("positions", "All quantities are non-negative.")]
    else:
        rationale = (f"The book has {plural(len(shorts), 'short position')} making up {share_words(share)} of "
                     f"gross exposure; short losses are unbounded and exposed to squeezes and borrow recalls.")
        ev = [field_evidence(f"positions[{i}].quantity", f"Short position {ds.positions[i].ticker}.")
              for i, _ in shorts]
    return Outcome(likelihood, fd.default_impact, C.ADEQUATE, rationale, ev)


def normality_reliance(inp: Inputs, fd: FactorDef) -> Outcome:
    medians = _method_medians(inp)
    fat = {m: r for m, r in medians.items() if m in fd.params["fat_tailed_methods"]}
    if "normal" not in medians or not fat:
        raise MissingInput("VaR from the normal method and from at least one fat-tailed method (evt or student_t)")
    normal = medians["normal"]
    fm, fr = max(fat.items(), key=lambda kv: kv[1].value)
    ratio = fr.value / normal.value
    likelihood = band_up(ratio, fd.params["ratio_cuts"])
    ev = normal.evidence("Median-ranked VaR, normal") + fr.evidence(f"Median-ranked VaR, {fm}")
    normal_verdicts = [r for r in inp.grid(VAR) if r.spec.params.get("method") == "normal" and r.output
                       and r.output.labels.get("backtest_verdict") in ("pass", "fail")]
    if any(r.output.labels["backtest_verdict"] == "fail" for r in normal_verdicts):
        control, ctl = C.WEAK, " and the normal-method backtest fails"
        ev += [label_evidence(r, "backtest_verdict") for r in normal_verdicts]
    elif normal_verdicts:
        control, ctl = C.ADEQUATE, " although the normal-method backtest passes"
        ev += [label_evidence(r, "backtest_verdict") for r in normal_verdicts]
    else:
        control, ctl = C.ADEQUATE, ""
    if ratio <= 1:
        rationale = (f"The fat-tailed estimate ({fm}, {fr.text}) does not exceed the normal estimate "
                     f"({normal.text}), so there is no sign that a normal assumption understates the tail{ctl}.")
    else:
        rationale = (f"The normal-method VaR ({normal.text}) is below the fat-tailed estimate ({fm}, {fr.text}), "
                     f"so relying on normality understates the tail{ctl}.")
    return Outcome(likelihood, fd.default_impact, control, rationale, ev)


RUBRIC: tuple[FactorDef, ...] = (
    FactorDef(
        "method_spread", "Model (method) risk",
        "How much the VaR estimate depends on the choice of method.", 4, method_spread,
        inputs=("comparison.method_spread['var']", "q1.var grid: var by method"),
        control_basis="Benchmarking across methods (effective challenge): strong with all six methods, "
                      "adequate with three or more, weak otherwise.",
        params={"spread_cuts": (1.25, 1.5, 2.0, 3.0), "strong_methods": 6, "adequate_methods": 3},
    ),
    FactorDef(
        "backtest_performance", "Backtest performance",
        "Whether the VaR forecasts were exceeded as often as they should be.", 4, backtest_performance,
        inputs=("comparison.label_counts['backtest_verdict']", "comparison.label_counts['basel_zone']",
                "q1.var: backtest_exceptions"),
        control_basis="Backtesting is itself the control; its results drive likelihood (control adequate).",
        params={"fail_share_cuts": (0.01, 0.25, 0.5, 0.75), "red_floor": 4, "yellow_floor": 3},
    ),
    FactorDef(
        "history_length", "History length",
        "Whether the return history is long enough to estimate tails and include a stress period.", 3,
        history_length,
        inputs=("q1.data_quality: history_days", "comparison.sensitivity (window_days, var)"),
        control_basis="Weak if the history cannot fill the longest (750-day) window, else adequate.",
        params={"days_cuts": (1250, 750, 500, 250), "long_window": 750, "window_effect": 0.25},
    ),
    FactorDef(
        "data_quality", "Market data quality",
        "Missing, stale and outlying returns that distort the estimate.", 3, data_quality,
        inputs=("q1.data_quality: label quality, missing_share, stale_series, outlier_count", "findings"),
        control_basis="Automated data-quality checks; weak if the data are rated poor.",
        params={"quality_likelihood": {"good": 1, "fair": 3, "poor": 4}},
    ),
    FactorDef(
        "concentration", "Position concentration",
        "Dependence of the portfolio on its largest non-cash position.", 3, concentration,
        inputs=("dataset.positions[*].quantity", "dataset.positions[*].price", "dataset.positions[*].asset_class"),
        control_basis="No limit framework in the data: adequate by default.",
        params={"weight_cuts": (0.10, 0.20, 0.30, 0.50), "n_eff_diversified": 10},
    ),
    FactorDef(
        "short_exposure", "Short exposure",
        "Share of gross exposure that is short (unbounded loss, squeezes, recalls).", 3, short_exposure,
        inputs=("dataset.positions[*].quantity",),
        control_basis="No borrow or stop-loss data: adequate by default.",
        params={"short_share_cuts": (1e-12, 0.10, 0.25, 0.40)},
    ),
    FactorDef(
        "normality_reliance", "Reliance on normality",
        "How much a Gaussian VaR understates fat-tailed estimates.", 4, normality_reliance,
        inputs=("q1.var grid: var for normal, evt, student_t", "q1.var: backtest_verdict (normal)"),
        control_basis="Weak if the normal-method backtest fails, else adequate.",
        params={"ratio_cuts": (1.1, 1.25, 1.5, 2.0), "fat_tailed_methods": ("evt", "student_t")},
    ),
)
