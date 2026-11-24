"""Rationale drafters (``ports.RationaleDrafter``) that need no language model.

``ScriptedDrafter`` returns canned text per factor id. It is used in tests and demos to exercise the
LLM path of the graph (draft -> verify -> accept/reject) deterministically and offline.
"""

from __future__ import annotations

import threading

from riskbot.contract.types import QualitativeAssessment, VariationResult


class ScriptedDrafter:
    """A ``RationaleDrafter`` that returns ``responses`` (factor_id -> rationale) verbatim.

    Only factor ids present in the assessment are returned, mirroring a well-behaved drafter. Every call
    is recorded in ``calls`` (the factor ids it was asked about) so tests can assert it ran.
    """

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = dict(responses)
        self.calls: list[list[str]] = []
        self._lock = threading.Lock()

    def draft(self, assessment: QualitativeAssessment, results: list[VariationResult]) -> dict[str, str]:
        ids = [f.factor_id for f in assessment.factors]
        with self._lock:
            self.calls.append(ids)
        return {fid: text for fid, text in self.responses.items() if fid in ids}
