"""Q3 transition-risk math: carbon-price valuation shock, footprint metrics and data quality.

Exports (CONTRACT.md section 2):
* ``models()`` -> [TransitionModel (q3.transition), DataQualityModel (q3.data_quality)]
* ``sample_dataset(seed=0)`` -> deterministic synthetic ``ClimatePortfolio``

All scenario paths, pass-through rates and pathway parameters are illustrative (see README.md).
"""

from __future__ import annotations

from riskbot.contract.ports import Model

from .data_quality import DataQualityModel
from .sample import sample_dataset
from .transition import TransitionModel

__all__ = ["models", "sample_dataset", "TransitionModel", "DataQualityModel"]


def models() -> list[Model]:
    """Fresh model instances for catalog.Q3_TRANSITION and catalog.Q3_DATA_QUALITY."""
    return [TransitionModel(), DataQualityModel()]
