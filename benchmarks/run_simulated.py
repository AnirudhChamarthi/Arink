"""Benchmark A: simulated truth (protocol section 3).

Runs the production rolling VaR models on simulated paths whose true conditional VaR is known,
then scores coverage, test behaviour, Basel zones, bias, RMSE and tick loss.

    python benchmarks/run_simulated.py            # full protocol: 200 paths per DGP
    python benchmarks/run_simulated.py --quick    # smoke test: 10 paths, not for citation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from scipy import stats

import common  # noqa: F401  (sets sys.path)
from dgp import DGPS, TEST_DAYS, WINDOW, simulate
from models.backtest import basel_traffic_light, christoffersen_independence, kupiec_pof, rolling_var

CONFIDENCES = (0.975, 0.99)
METHODS = ("historical", "parametric", "ewma")
ORACLE = "oracle (true VaR)"
FULL_PATHS = 200
BLOCK = 250


def tick_loss(losses: np.ndarray, q: np.ndarray, c: float) -> np.ndarray:
    return (c - (losses <= q)) * (losses - q)


def _score(losses, var_hat, true_var, c) -> dict:
    exc = losses > var_hat
    n_exc = int(exc.sum())
    kup = kupiec_pof(n_exc, exc.size, c)
    ind = christoffersen_independence(exc)
    rel = (var_hat - true_var) / true_var
    zones = []
    if c == 0.99:
        for b in range(0, exc.size - BLOCK + 1, BLOCK):
            zones.append(basel_traffic_light(int(exc[b : b + BLOCK].sum()), BLOCK, c))
    return {
        "exceptions": n_exc,
        "kupiec_reject": bool(kup.reject),
        "independence_reject": bool(ind.reject),
        "rel_bias": float(rel.mean()),
        "rel_sq": float((rel**2).mean()),
        "tick": float(tick_loss(losses, var_hat, c).mean()),
        "tick_oracle": float(tick_loss(losses, true_var, c).mean()),
        "zones": zones,
    }


def run_path(args) -> dict:
    dgp, k = args
    path = simulate(dgp, k)
    losses = -path.returns[WINDOW:]
    out = {}
    for c in CONFIDENCES:
        true_var = path.true_var(c)[WINDOW:]
        out[f"{ORACLE}|{c}"] = _score(losses, true_var, true_var, c)
        for m in METHODS:
            var_hat = rolling_var(path.returns, c, window=WINDOW, method=m)
            out[f"{m}|{c}"] = _score(losses, var_hat, true_var, c)
    return {"dgp": dgp, "path": k, "scores": out}


def aggregate(path_results: list[dict], n_paths: int) -> list[dict]:
    rows = []
    for dgp in DGPS:
        per = [p for p in path_results if p["dgp"] == dgp]
        for c in CONFIDENCES:
            for m in (ORACLE, *METHODS):
                s = [p["scores"][f"{m}|{c}"] for p in per]
                exc_rates = np.array([x["exceptions"] / TEST_DAYS for x in s])
                zones = [z for x in s for z in x["zones"]]
                tick = np.mean([x["tick"] for x in s])
                tick_oracle = np.mean([x["tick_oracle"] for x in s])
                row = {
                    "dgp": dgp,
                    "method": m,
                    "confidence": c,
                    "paths": n_paths,
                    "target_exception_rate": round(1 - c, 6),
                    "exception_rate_mean": float(exc_rates.mean()),
                    "exception_rate_p05": float(np.quantile(exc_rates, 0.05)),
                    "exception_rate_p95": float(np.quantile(exc_rates, 0.95)),
                    "kupiec_reject_rate": float(np.mean([x["kupiec_reject"] for x in s])),
                    "independence_reject_rate": float(np.mean([x["independence_reject"] for x in s])),
                    "rel_bias": float(np.mean([x["rel_bias"] for x in s])),
                    "rel_rmse": float(np.sqrt(np.mean([x["rel_sq"] for x in s]))),
                    "excess_tick_loss_pct": float((tick / tick_oracle - 1.0) * 100.0),
                }
                if zones:
                    row["basel_blocks"] = len(zones)
                    for z in ("green", "yellow", "red"):
                        row[f"basel_{z}"] = zones.count(z) / len(zones)
                rows.append(row)
    return rows


def basel_expected() -> dict:
    """Zone probabilities for a correct 99% model over 250 days (binomial)."""
    p = 0.01
    green = float(stats.binom.cdf(4, BLOCK, p))
    yellow = float(stats.binom.cdf(9, BLOCK, p) - green)
    return {"green": green, "yellow": yellow, "red": 1.0 - green - yellow}


def run(n_paths: int, workers: int) -> tuple[list[dict], list[dict]]:
    jobs = [(d, k) for d in DGPS for k in range(n_paths)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run_path, jobs, chunksize=4))
    return results, aggregate(results, n_paths)


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="10 paths per DGP; smoke test only")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    n_paths = 10 if args.quick else FULL_PATHS

    t0 = time.perf_counter()
    raw1, rows = run(n_paths, args.workers)
    elapsed = time.perf_counter() - t0
    raw2, _ = run(n_paths, args.workers)  # protocol 5: run twice, results must be identical
    d1, d2 = digest(raw1), digest(raw2)

    path = common.write_result(
        "simulated_quick" if args.quick else "simulated",
        {
            "citable": not args.quick,
            "design": {
                "paths_per_dgp": n_paths,
                "window": WINDOW,
                "test_days": TEST_DAYS,
                "confidences": list(CONFIDENCES),
                "methods": list(METHODS),
                "dgps": list(DGPS),
            },
            "basel_expected_correct_model_99": basel_expected(),
            "reproducibility": {"run1_sha256": d1, "run2_sha256": d2, "identical": d1 == d2},
            "runtime_seconds": round(elapsed, 1),
            "rows": rows,
        },
    )
    print(f"wrote {path} in {elapsed:.1f}s; reproducible={d1 == d2}")


if __name__ == "__main__":
    main()
