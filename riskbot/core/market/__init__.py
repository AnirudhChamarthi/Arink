"""Q1 market math: portfolio VaR / expected shortfall and market data quality.

Exports (CONTRACT.md section 2)
-------------------------------
``models()``          -> ``[VarModel(), DataQualityModel()]`` implementing ``catalog.Q1_VAR`` and
                         ``catalog.Q1_DATA_QUALITY``.
``sample_dataset(seed)`` -> deterministic synthetic ``MarketDataset``.

Model documentation: ``README.md`` in this package.
"""

from __future__ import annotations

from riskbot.contract.ports import Model

from .data_quality import DataQualityModel
from .sample import sample_dataset
from .var_model import VarModel


def models() -> list[Model]:
    """The Q1 models, in catalogue order."""
    return [VarModel(), DataQualityModel()]


__all__ = ["models", "sample_dataset", "VarModel", "DataQualityModel"]
