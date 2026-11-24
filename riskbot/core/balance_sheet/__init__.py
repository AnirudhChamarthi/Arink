"""Q2 balance-sheet math: rate shock plus deposit run, reverse stress test and data quality.

Exports (CONTRACT.md section 2): ``models()`` and ``sample_dataset(seed=0)``. See README.md for the model
documentation (formulas, assumptions, limitations, references).
"""

from __future__ import annotations

from riskbot.contract.ports import Model

from .data_quality import DataQualityModel
from .resilience import ResilienceModel
from .reverse_stress import ReverseStressModel
from .sample import sample_dataset


def models() -> list[Model]:
    """One instance of each Q2 model: q2.resilience, q2.reverse_stress, q2.data_quality."""
    return [ResilienceModel(), ReverseStressModel(), DataQualityModel()]


__all__ = ["models", "sample_dataset", "ResilienceModel", "ReverseStressModel", "DataQualityModel"]
