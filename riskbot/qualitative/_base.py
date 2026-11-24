"""Building blocks of a rubric: a factor definition (data) and the outcome a rule returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping

from riskbot.contract.types import ControlStrength, Evidence

from ._inputs import Inputs


@dataclass(frozen=True)
class Outcome:
    """What a rule decides for one factor. Ratings are derived later with ``rules.rate``."""

    likelihood: int
    impact: int
    control: ControlStrength
    rationale: str
    evidence: list[Evidence]

    def __post_init__(self) -> None:
        if not (1 <= self.likelihood <= 5 and 1 <= self.impact <= 5):
            raise ValueError(f"likelihood/impact out of range: {self.likelihood}, {self.impact}")
        if not self.evidence:
            raise ValueError("a rule outcome must cite at least one piece of evidence")


Rule = Callable[[Inputs, "FactorDef"], Outcome]


@dataclass(frozen=True)
class FactorDef:
    """One row of a rubric table.

    ``params`` holds the thresholds the rule uses, so the table (and the README generated from the same
    numbers) is the single place where they are defined. ``inputs`` and ``control_basis`` document
    what the rule reads and what counts as a control.
    """

    factor_id: str
    name: str
    description: str
    default_impact: int
    rule: Rule
    inputs: tuple[str, ...]
    control_basis: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        if not 1 <= self.default_impact <= 5:
            raise ValueError("default_impact must be 1-5")
