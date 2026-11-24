"""Canonical hashing and id rules. Every component must use these so ids agree everywhere."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, pydantic models dumped in JSON mode."""

    def default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "tolist"):  # numpy arrays and scalars
            return o.tolist()
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")

    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=default, allow_nan=False)


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def model_input_hash(model_id: str, dataset: Any, params: dict[str, Any], seed: int) -> str:
    """Input hash for a model call; also the basis of the trace id."""
    return sha256_hex({"model_id": model_id, "dataset": dataset, "params": params, "seed": seed})


def trace_id(model_id: str, input_hash: str, suffix: str = "") -> str:
    """'<model_id>-<12 hex>' plus an optional '-<suffix>' when one call emits several traces."""
    return f"{model_id}-{input_hash[:12]}" + (f"-{suffix}" if suffix else "")


def variation_id(model_id: str, params: dict[str, Any]) -> str:
    return "v" + sha256_hex({"model_id": model_id, "params": params})[:10]


def derive_seed(run_seed: int, variation_id_: str) -> int:
    """Per-variation seed in [0, 2**32): independent of execution order."""
    return int(sha256_hex({"seed": run_seed, "variation": variation_id_})[:8], 16)


def run_input_hash(question: str, dataset: Any, plan: Any, seed: int) -> str:
    return sha256_hex({"question": question, "dataset": dataset, "plan": plan, "seed": seed})
