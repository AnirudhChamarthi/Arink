"""Benchmark C: engineering (protocol section 5): latency and test inventory.

    python benchmarks/run_performance.py
"""

from __future__ import annotations

import re
import statistics
import subprocess
import sys
import time

import numpy as np

import common
from models.backtest import run_backtest
from models.explain import explain_parametric_var
from models.var import historical_var, montecarlo_var, parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition

SIZES = (10, 100, 500)
REPEATS = 7
SEED = 20261123


def portfolio(n: int) -> EnrichedPortfolio:
    rng = np.random.default_rng([SEED, n])
    market = rng.normal(0, 0.01, 252)
    positions = []
    for i in range(n):
        r = 0.8 * market + rng.normal(0, 0.008, 252)
        positions.append(
            EnrichedPosition(
                ticker=f"S{i:03d}", asset_class=AssetClass.EQUITY,
                quantity=float(rng.integers(-50, 200) or 1), cost_price=100.0, currency="USD",
                current_price=float(rng.uniform(20, 300)), returns_252d=r.tolist(), implied_vol=0.25,
                risk_free_rate=0.04, esg_score=60.0, carbon_intensity=50.0,
            )
        )
    return EnrichedPortfolio(portfolio_name=f"synthetic-{n}", base_currency="USD", positions=positions)


def median_ms(fn) -> float:
    fn()  # warm-up
    times = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times)


def latency() -> list[dict]:
    rows = []
    for n in SIZES:
        pf = portfolio(n)
        cases = {
            "parametric_var": lambda: parametric_var(pf, 0.99, 1),
            "historical_var": lambda: historical_var(pf, 0.99, 1),
            "montecarlo_var (10,000 sims)": lambda: montecarlo_var(pf, 0.99, 1, n_sims=10_000),
            "parametric_var trace": lambda: explain_parametric_var(pf, 0.99, 1),
        }
        for name, fn in cases.items():
            rows.append({"calculation": name, "positions": n, "median_ms": round(median_ms(fn), 3)})
    r = np.random.default_rng(SEED).normal(0, 0.01, 1250)
    for m in ("historical", "parametric", "ewma"):
        rows.append({
            "calculation": f"rolling backtest, {m} (1,000 days)", "positions": 1,
            "median_ms": round(median_ms(lambda m=m: run_backtest(r, 0.99, 250, m)), 3),
        })
    return rows


def test_inventory() -> dict:
    def collect(path: str) -> tuple[int, str]:
        out = subprocess.run([sys.executable, "-m", "pytest", "-q", path],
                             cwd=common.REPO_ROOT / ("engine" if path == "tests" else "."),
                             capture_output=True, text=True)
        tail = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tail)) else 0
        return passed, tail

    engine_passed, engine_tail = collect("tests")
    bench_passed, bench_tail = collect("benchmarks/tests")
    return {
        "engine_tests_passed": engine_passed,
        "engine_summary": engine_tail,
        "harness_tests_passed": bench_passed,
        "harness_summary": bench_tail,
        "all_passed": "failed" not in engine_tail + bench_tail and "error" not in engine_tail + bench_tail,
    }


def main() -> None:
    rows = latency()
    inv = test_inventory()
    path = common.write_result("performance", {"citable": True, "repeats": REPEATS, "latency": rows, "tests": inv})
    print(f"wrote {path}")
    for r in rows:
        print(f"{r['calculation']:40} n={r['positions']:<4} {r['median_ms']:>10.3f} ms")
    print(inv)


if __name__ == "__main__":
    main()
