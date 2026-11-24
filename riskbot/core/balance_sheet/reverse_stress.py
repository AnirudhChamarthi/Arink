"""``q2.reverse_stress``: smallest deposit outflow / rate shock that breaches a constraint.

Both searches call ``engine.evaluate`` (the same calculation as ``q2.resilience``) with that model's default
thresholds, base credit severity and default fire-sale impact.

Method
------
1. Coarse grid (11 points over the range). The breach indicator must be non-decreasing and the constrained
   quantity (capital ratio or LCR after stress) non-increasing along the grid; otherwise a warning is issued
   (the search then still returns the smallest breach found on the grid, refined by bisection).
2. If the lower end already breaches the breakeven is the lower end; if the upper end does not breach the
   metric is omitted and the label is ``no``.
3. Otherwise bisection on the first grid bracket ``[lo, hi]`` with ``breach(lo) = False`` and
   ``breach(hi) = True`` until ``hi - lo <= tol``; the reported breakeven is ``hi`` (it breaches, and
   ``hi - tol`` does not under monotonicity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from riskbot.contract import catalog
from riskbot.contract.conformance import resolve_params
from riskbot.contract.hashing import model_input_hash
from riskbot.contract.tracing import TraceBuilder
from riskbot.contract.types import BankBalanceSheet, ModelOutput, ModelSpec, Unit

from . import engine
from .resilience import reconciliation_findings
from .validation import check_structure, coerce_balance_sheet

GRID_POINTS = 11
RATE_RANGE_BP = (0.0, 1000.0)
OUTFLOW_RANGE = (0.0, 1.0)
_RES_DEFAULTS = {p.name: p.default for p in catalog.Q2_RESILIENCE.params}

ASSUMPTIONS = [
    "Uses the q2.resilience calculation with its default thresholds (capital "
    f"{_RES_DEFAULTS['capital_threshold']}, LCR {_RES_DEFAULTS['lcr_threshold']}), base credit severity (q = 0.90) "
    f"and default fire-sale impact ({_RES_DEFAULTS['fire_sale_impact']}); thresholds are illustrative.",
    "Outflow search: every deposit segment loses the same fraction x in 30 days and wholesale funding maturing "
    "within 30 days is not rolled over; the rate shock is held at rate_shock_bp.",
    "Rate search: parallel shocks from 0 to 1000 bp with the slow-run run-off rates.",
    "A breach is capital ratio < threshold (target capital) or LCR < threshold or a liquidity shortfall "
    "(target liquidity). Bisection assumes the breach region is an upper interval; monotonicity is checked on an "
    "11-point grid and a violation is reported as a warning.",
    "The second-order duration/convexity approximation loses accuracy for very large shocks (beyond D/C the "
    "approximated loss shrinks again), which can make the rate search non-monotone.",
]


@dataclass
class Search:
    name: str
    lo_bound: float
    hi_bound: float
    tol: float
    grid: list[dict] = field(default_factory=list)
    iterations: list[dict] = field(default_factory=list)
    monotone: bool = True
    found: bool = False
    value: float | None = None
    bracket: tuple[float, float] | None = None
    check: dict | None = None


def bisect_breakeven(fn: Callable[[float], engine.StressResult], target: str, lo: float, hi: float, tol: float,
                     name: str = "x") -> Search:
    """Smallest ``x`` in [lo, hi] whose stress result breaches ``target`` (grid scan + bisection)."""
    s = Search(name, lo, hi, tol)
    xs = [lo + (hi - lo) * i / (GRID_POINTS - 1) for i in range(GRID_POINTS)]
    vals, breaches = [], []
    for x in xs:
        r = fn(x)
        v, b = engine.constraint_value(r, target), engine.is_breach(r, target)
        vals.append(v)
        breaches.append(b)
        s.grid.append({name: x, "constraint": v, "breach": b})
    inc_breach = any(b1 and not b2 for b1, b2 in zip(breaches, breaches[1:]))
    rising = any(v2 > v1 + 1e-9 * max(1.0, abs(v1)) for v1, v2 in zip(vals, vals[1:]))
    s.monotone = not (inc_breach or rising)
    if breaches[0]:
        s.found, s.value, s.bracket = True, lo, (lo, lo)
        return s
    first = next((i for i, b in enumerate(breaches) if b), None)
    if first is None:
        return s
    a, b = xs[first - 1], xs[first]
    s.bracket = (a, b)
    k = 0
    while b - a > tol:
        k += 1
        m = 0.5 * (a + b)
        r = fn(m)
        br = engine.is_breach(r, target)
        s.iterations.append({"k": k, "lo": a, "hi": b, "mid": m, "constraint": engine.constraint_value(r, target),
                             "breach": br})
        if br:
            b = m
        else:
            a = m
    s.found, s.value = True, b
    r_hi, r_lo = fn(b), fn(max(lo, b - tol))
    s.check = {"at": b, "constraint_at": engine.constraint_value(r_hi, target), "breach_at": engine.is_breach(r_hi, target),
               "at_minus_tol": max(lo, b - tol), "constraint_at_minus_tol": engine.constraint_value(r_lo, target),
               "breach_at_minus_tol": engine.is_breach(r_lo, target)}
    return s


def outflow_scenario(p: dict[str, Any], x: float) -> engine.Scenario:
    return engine.Scenario(rate_shock_bp=float(p["rate_shock_bp"]), run_speed="uniform", uniform_outflow=x,
                           loss_severity="base", htm_treatment=p["htm_treatment"],
                           capital_threshold=_RES_DEFAULTS["capital_threshold"],
                           lcr_threshold=_RES_DEFAULTS["lcr_threshold"],
                           fire_sale_impact=_RES_DEFAULTS["fire_sale_impact"])


def rate_scenario(p: dict[str, Any], bp: float) -> engine.Scenario:
    return engine.Scenario(rate_shock_bp=bp, run_speed="slow", loss_severity="base",
                           htm_treatment=p["htm_treatment"], capital_threshold=_RES_DEFAULTS["capital_threshold"],
                           lcr_threshold=_RES_DEFAULTS["lcr_threshold"],
                           fire_sale_impact=_RES_DEFAULTS["fire_sale_impact"])


def run_searches(bs: BankBalanceSheet, p: dict[str, Any]) -> tuple[Search, Search]:
    tgt = p["target"]
    out = bisect_breakeven(lambda x: engine.evaluate(bs, outflow_scenario(p, x)), tgt, *OUTFLOW_RANGE,
                           p["tolerance"], name="outflow_fraction")
    rate = bisect_breakeven(lambda bp: engine.evaluate(bs, rate_scenario(p, bp)), tgt, *RATE_RANGE_BP,
                            p["tolerance"] * 1000.0, name="rate_shock_bp")
    return out, rate


class ReverseStressModel:
    spec: ModelSpec = catalog.Q2_REVERSE_STRESS

    def run(self, dataset: Any, params: dict[str, Any], seed: int) -> ModelOutput:
        mid = self.spec.model_id
        bs = coerce_balance_sheet(dataset, mid)
        eff = resolve_params(self.spec, params)
        check_structure(bs, mid, for_stress=True)
        out, rate = run_searches(bs, eff)
        h = model_input_hash(mid, bs, eff, seed)
        tb = TraceBuilder(mid, f"{self.spec.title} ({eff['target']}): {bs.name}", h, assumptions=ASSUMPTIONS,
                          inputs={"params": eff, "resilience_defaults": _RES_DEFAULTS, "grid_points": GRID_POINTS})
        metrics, result = {}, {}
        thr = _RES_DEFAULTS["capital_threshold"] if eff["target"] == "capital" else _RES_DEFAULTS["lcr_threshold"]
        quantity = "CET1/RWA" if eff["target"] == "capital" else "LCR"
        for s, key, unit, sym, desc in (
            (out, "breakeven_deposit_outflow", Unit.FRACTION, "x",
             f"uniform deposit outflow at {eff['rate_shock_bp']} bp"),
            (rate, "breakeven_rate_shock_bp", Unit.BASIS_POINTS, r"\Delta y_{bp}", "rate shock with a slow run"),
        ):
            prefix = key.replace("breakeven_", "")
            tb.step(f"{prefix}_grid", f"Coarse grid: {desc}",
                    rf"g({sym}) = {quantity}'({sym}),\ \text{{breach}} \iff g < {thr}",
                    f"{GRID_POINTS} points on [{s.lo_bound:g}, {s.hi_bound:g}]; monotone = {s.monotone}",
                    table=s.grid, note="" if s.monotone else "Monotonicity violated on the grid.")
            if not s.monotone:
                tb.warn(f"{key}: breach indicator or {quantity} not monotone on the coarse grid; the smallest grid "
                        "breach was refined but other breakeven points may exist")
            br = "none" if s.bracket is None else f"[{s.bracket[0]:g}, {s.bracket[1]:g}]"
            tb.step(f"{prefix}_bisection", f"Bisection: {desc}",
                    r"m = (lo+hi)/2;\ \text{breach}(m) \Rightarrow hi = m \text{ else } lo = m;\ "
                    r"\text{stop when } hi - lo \le tol",
                    f"bracket {br}, tol = {s.tol:g}, {len(s.iterations)} iterations",
                    table=s.iterations or None)
            if s.found:
                chk = s.check
                sub = f"{sym}* = {s.value:.6g}"
                if chk:
                    sub += (f"; {quantity}'({chk['at']:.6g}) = {chk['constraint_at']:.6f} (breach {chk['breach_at']}), "
                            f"{quantity}'({chk['at_minus_tol']:.6g}) = {chk['constraint_at_minus_tol']:.6f} "
                            f"(breach {chk['breach_at_minus_tol']})")
                else:
                    sub += " (lower end of the range already breaches)"
                tb.step(key, f"Breakeven: {desc}", rf"{sym}^* = \min\{{{sym}: {quantity}'({sym}) < {thr}\}}", sub,
                        value=s.value, unit=unit)
                metrics[key] = tb.metric(key, s.value, unit)
                result[key] = s.value
            else:
                tb.step(key, f"Breakeven: {desc}", rf"{sym}^* = \min\{{{sym}: {quantity}'({sym}) < {thr}\}}",
                        f"no breach within [{s.lo_bound:g}, {s.hi_bound:g}]; metric omitted")
        labels = {"outflow_found": "yes" if out.found else "no", "rate_found": "yes" if rate.found else "no"}
        return ModelOutput(model_id=mid, params=eff, metrics=metrics, labels=labels, traces=[tb.build(result)],
                           findings=reconciliation_findings(bs), warnings=tb.warnings)
