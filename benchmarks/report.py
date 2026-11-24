"""Generate BENCHMARKS.md from benchmarks/results/*.json (protocol section 8).

Every number in the report, including the headline statements, is computed here from the result
files. Do not edit BENCHMARKS.md by hand; re-run this script.

    python benchmarks/report.py
"""

from __future__ import annotations

import json
from pathlib import Path

import common

OUT = common.REPO_ROOT / "BENCHMARKS.md"
ORACLE = "oracle (true VaR)"
DGP_LABEL = {
    "normal_iid": "Normal, constant volatility (control)",
    "garch_normal": "GARCH(1,1), normal shocks",
    "garch_t5": "GARCH(1,1), fat-tailed shocks (t, ν=5)",
    "regime_stress": "Calm regime with a 125-day stress episode (3× volatility)",
}


def load(name: str) -> dict | None:
    p = common.RESULTS_DIR / f"{name}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def pct(x: float, d: int = 1) -> str:
    return f"{100 * x:.{d}f}%"


def row(rows, dgp, method, c):
    return next(r for r in rows if r["dgp"] == dgp and r["method"] == method and r["confidence"] == c)


def headlines(sim: dict, perf: dict | None) -> list[str]:
    rows = sim["rows"]
    methods = sim["design"]["methods"]
    out = []

    oracle = [r for r in rows if r["method"] == ORACLE]
    kr = [r["kupiec_reject_rate"] for r in oracle]
    greens = [r["basel_green"] for r in oracle if "basel_green" in r]
    exp_green = sim["basel_expected_correct_model_99"]["green"]
    out.append(
        f"**Harness is calibrated.** Scoring the true VaR, the Kupiec test rejected in {pct(min(kr))}–{pct(max(kr))} "
        f"of paths (nominal 5%), and {pct(min(greens))}–{pct(max(greens))} of 250-day blocks were green "
        f"(binomial expectation {pct(exp_green)})."
    )

    for dgp in ("garch_normal", "garch_t5", "regime_stress"):
        cand = [row(rows, dgp, m, 0.99) for m in methods]
        best = min(cand, key=lambda r: r["excess_tick_loss_pct"])
        worst = max(cand, key=lambda r: r["excess_tick_loss_pct"])
        out.append(
            f"**{DGP_LABEL[dgp]}, 99%:** best method by tick loss was `{best['method']}` "
            f"({best['excess_tick_loss_pct']:.1f}% above the oracle, Kupiec rejection {pct(best['kupiec_reject_rate'], 0)}); "
            f"worst was `{worst['method']}` ({worst['excess_tick_loss_pct']:.1f}% above the oracle, "
            f"Kupiec rejection {pct(worst['kupiec_reject_rate'], 0)})."
        )

    t5 = {m: row(rows, "garch_t5", m, 0.99) for m in methods}
    out.append(
        f"**Limitation found: normal quantiles under fat tails.** On fat-tailed GARCH data at 99%, "
        f"`ewma` tracked volatility best (relative RMSE {t5['ewma']['rel_rmse']:.3f}) but under-stated VaR by "
        f"{pct(-t5['ewma']['rel_bias'])} on average, with a {pct(t5['ewma']['exception_rate_mean'], 2)} exception "
        f"rate against a 1% target. This is the gap that filtered historical simulation and EVT (roadmap M1) are meant to close."
    )

    iid = row(rows, "normal_iid", "historical", 0.99)
    out.append(
        f"**Small-sample bias of historical VaR.** Even on i.i.d. normal data, 250-day historical VaR at 99% had a "
        f"{pct(iid['exception_rate_mean'], 2)} exception rate (target 1%), consistent with order-statistic theory for a "
        f"250-observation empirical quantile."
    )

    rep = sim["reproducibility"]
    out.append(
        f"**Reproducible.** The full simulated benchmark ({sim['design']['paths_per_dgp']} paths × "
        f"{len(sim['design']['dgps'])} processes × {len(methods)} methods × {len(sim['design']['confidences'])} confidence levels) "
        f"was run twice with {'identical' if rep['identical'] else 'DIFFERENT'} results (SHA-256 `{rep['run1_sha256'][:12]}…`)."
    )

    if perf:
        lat = {(r["calculation"], r["positions"]): r["median_ms"] for r in perf["latency"]}
        t = perf["tests"]
        out.append(
            f"**Engineering.** {t['engine_tests_passed']} engine tests and {t['harness_tests_passed']} benchmark-harness "
            f"tests pass. On a 500-position portfolio, parametric VaR takes {lat[('parametric_var', 500)]:.1f} ms, the full "
            f"step-by-step trace {lat[('parametric_var trace', 500)]:.1f} ms and 10,000-path Monte Carlo VaR "
            f"{lat[('montecarlo_var (10,000 sims)', 500)]:.0f} ms (median of {perf['repeats']}; hardware below)."
        )
    return out


def sim_table(sim: dict, c: float) -> list[str]:
    lines = [
        "| Process | Method | Exception rate (5th–95th pct) | Kupiec reject | Independence reject | Rel. bias | Rel. RMSE | Excess tick loss |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in (r for r in sim["rows"] if r["confidence"] == c):
        lines.append(
            f"| {r['dgp']} | {r['method']} | {pct(r['exception_rate_mean'], 2)} ({pct(r['exception_rate_p05'], 2)}–"
            f"{pct(r['exception_rate_p95'], 2)}) | {pct(r['kupiec_reject_rate'], 0)} | {pct(r['independence_reject_rate'], 0)} | "
            f"{r['rel_bias']:+.3f} | {r['rel_rmse']:.3f} | {r['excess_tick_loss_pct']:.1f}% |"
        )
    return lines


def zone_table(sim: dict) -> list[str]:
    e = sim["basel_expected_correct_model_99"]
    lines = [
        f"Expected for a correct model: green {pct(e['green'])}, yellow {pct(e['yellow'])}, red {pct(e['red'], 2)}.",
        "",
        "| Process | Method | Blocks | Green | Yellow | Red |",
        "|---|---|---|---|---|---|",
    ]
    for r in (r for r in sim["rows"] if r["confidence"] == 0.99):
        lines.append(f"| {r['dgp']} | {r['method']} | {r['basel_blocks']} | {pct(r['basel_green'])} | "
                     f"{pct(r['basel_yellow'])} | {pct(r['basel_red'])} |")
    return lines


def market_section(mkt: dict | None) -> list[str]:
    if not mkt:
        return [
            "_Pending._ This benchmark downloads index data and must be run on a machine with internet access:",
            "`python benchmarks/run_market.py`, then `python benchmarks/report.py`.",
        ]
    lines = [f"Source: {mkt['source']}. Sample {mkt['design']['start']} to {mkt['design']['end']}.", ""]
    lines += ["| Index | Observations | First | Last | Data hash |", "|---|---|---|---|---|"]
    for s in mkt["series"]:
        lines.append(f"| {s['name']} | {s['observations']} | {s['first_date']} | {s['last_date']} | `{s['data_sha256_16']}` |")
    lines += ["", "| Index | Window | Method | Conf. | Days | Exceptions (expected) | Rate | Kupiec p | P(≥ this many) | Yellow/red blocks |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for s in mkt["series"]:
        for r in s["rows"]:
            yr = pct(r["basel_yellow_or_red_share"], 0) if "basel_yellow_or_red_share" in r else ""
            lines.append(
                f"| {s['name']} | {r['window']} | {r['method']} | {r['confidence']} | {r['days']} | {r['exceptions']} "
                f"({r['expected']}) | {pct(r['exception_rate'], 2)} | {r['kupiec_p']:.3f} | {r['binom_p_at_least']:.3f} | {yr} |"
            )
    return lines


def env_table(res: dict) -> list[str]:
    e = res["environment"]
    return [f"Commit `{res['git_commit']}`, generated {res['generated_at']}, protocol v{res['protocol_version']}. "
            f"Python {e['python']}, numpy {e['numpy']}, scipy {e['scipy']}, {e['os']} ({e['machine']}, {e['cpu_count']} CPUs)."]


def main() -> None:
    sim, perf, mkt = load("simulated"), load("performance"), load("market")
    if not sim:
        raise SystemExit("results/simulated.json missing: run benchmarks/run_simulated.py first")

    L = [
        "# Benchmarks",
        "",
        "<!-- Generated by benchmarks/report.py from benchmarks/results/*.json. Do not edit by hand. -->",
        "",
        f"Produced under [benchmark protocol v{sim['protocol_version']}](benchmarks/PROTOCOL.md), which was fixed before any results "
        "existed. Simulated results are labelled as simulated. Every number below is computed from the committed result files and "
        "can be reproduced with the commands in the protocol.",
        "",
        "## Headline results",
        "",
        *[f"- {h}" for h in headlines(sim, perf)],
        "",
        "## A. Simulated truth (VaR methods vs a known true VaR)",
        "",
        "Simulated data. 200 paths per process; 250-day estimation window; 1,000 out-of-sample test days per path. "
        "Rejection rates are the share of paths where the test rejects at 5%; a correct model should be near 5%. "
        "Excess tick loss is the method's quantile loss relative to scoring with the true VaR (0% is perfect).",
        "",
        *[f"- **{k}**: {v}" for k, v in DGP_LABEL.items()],
        "",
        "### 99% confidence",
        "",
        *sim_table(sim, 0.99),
        "",
        "### 97.5% confidence",
        "",
        *sim_table(sim, 0.975),
        "",
        "### Basel traffic-light zones (99%, non-overlapping 250-day blocks)",
        "",
        *zone_table(sim),
        "",
        *env_table(sim),
        "",
        "## B. Historical market data",
        "",
        *market_section(mkt),
        "",
        "## C. Engineering",
        "",
    ]
    if perf:
        L += ["| Calculation | Positions | Median time (ms) |", "|---|---|---|"]
        L += [f"| {r['calculation']} | {r['positions']} | {r['median_ms']:.3f} |" for r in perf["latency"]]
        t = perf["tests"]
        L += ["", f"Tests: engine `{t['engine_summary']}`; benchmark harness `{t['harness_summary']}`.", "", *env_table(perf)]
    else:
        L += ["_Pending: run `python benchmarks/run_performance.py`._"]
    L += [
        "",
        "## What these numbers do and do not show",
        "",
        "- Simulated results show how methods behave when the truth is known; they do not prove performance on real portfolios.",
        "- Market results use index returns as a public stand-in; banks backtest against portfolio P&L.",
        "- Latency depends on hardware; compare only within the same environment.",
        "- Planned benchmarks (mutation score, trace fidelity, verifier recall, REST/MCP parity, FHS and EVT methods) are listed in "
        "the protocol and are not yet reported.",
        "",
    ]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
