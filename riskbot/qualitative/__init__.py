"""Qualitative assessment (judgment, clearly labelled): rubric-driven pre-fill of risk factors.

Entry point: ``assessor() -> Assessor`` (see ``contract.ports.Assessor``). Rubrics are data
(``rubrics.RUBRICS``); each factor's rule turns model outputs, the comparison and dataset fields into a
likelihood, impact and control strength with cited evidence. See README.md for every rule.
"""

from __future__ import annotations

from riskbot.contract.ports import Assessor

from .assessor import METHOD_NOTE, RubricAssessor
from .rubrics import CONTRACT_FACTOR_IDS, RUBRICS


def assessor() -> Assessor:
    """Return the rubric-based assessor implementing ``contract.ports.Assessor``."""
    return RubricAssessor()


__all__ = ["assessor", "RubricAssessor", "RUBRICS", "CONTRACT_FACTOR_IDS", "METHOD_NOTE"]
