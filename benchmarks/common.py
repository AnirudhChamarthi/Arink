"""Shared helpers for the benchmark runners: import path, environment record, result files."""

from __future__ import annotations

import datetime as _dt
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = REPO_ROOT / "engine"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
PROTOCOL_VERSION = "1.0"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def environment() -> dict:
    import numpy
    import scipy

    try:
        import os

        cpus = os.cpu_count()
    except Exception:
        cpus = None
    return {
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": cpus,
    }


def write_result(name: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "benchmark": name,
        "protocol_version": PROTOCOL_VERSION,
        "git_commit": git_commit(),
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": environment(),
        **payload,
    }
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
