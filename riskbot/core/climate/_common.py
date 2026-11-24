"""Helpers shared by the Q3 models (dataset coercion, formatting)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from riskbot.contract.errors import ValidationFailed
from riskbot.contract.types import ClimatePortfolio

MUSD = 1_000_000.0  # monetary dataset fields are in currency units; intensities use USD millions


def as_portfolio(dataset: Any, model_id: str) -> ClimatePortfolio:
    """Return the dataset as a ClimatePortfolio or raise ValidationFailed (wrong kind / invalid)."""
    if isinstance(dataset, ClimatePortfolio):
        return dataset
    kind = getattr(dataset, "kind", None)
    if kind is None and isinstance(dataset, dict):
        kind = dataset.get("kind")
        if kind == "climate":
            try:
                return ClimatePortfolio.model_validate(dataset)
            except ValidationError as exc:
                raise ValidationFailed(f"invalid climate dataset: {exc}", model_id=model_id) from None
    raise ValidationFailed(
        f"{model_id} needs a dataset of kind 'climate', got {kind!r}", model_id=model_id, kind=str(kind)
    )


def fmt(x: float, digits: int = 4) -> str:
    """Compact number formatting for trace substitutions."""
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1e15 or ax < 1e-3:
        return f"{x:.{digits}e}"
    return f"{x:,.{digits}f}".rstrip("0").rstrip(".")
