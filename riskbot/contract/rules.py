"""Shared business rules, defined once so every component (and the UI) agrees."""

from __future__ import annotations

from .types import ControlStrength, Rating

_ORDER = [Rating.LOW, Rating.MEDIUM, Rating.HIGH, Rating.CRITICAL]


def inherent_rating(likelihood: int, impact: int) -> Rating:
    """Score = likelihood x impact (1-25): 1-4 low, 5-9 medium, 10-15 high, 16-25 critical."""
    if not (1 <= likelihood <= 5 and 1 <= impact <= 5):
        raise ValueError("likelihood and impact must be 1-5")
    score = likelihood * impact
    if score <= 4:
        return Rating.LOW
    if score <= 9:
        return Rating.MEDIUM
    if score <= 15:
        return Rating.HIGH
    return Rating.CRITICAL


def residual_rating(inherent: Rating, control: ControlStrength) -> Rating:
    """Weak controls leave the rating unchanged; adequate lowers it one level; strong lowers it two."""
    steps = {ControlStrength.WEAK: 0, ControlStrength.ADEQUATE: 1, ControlStrength.STRONG: 2}[control]
    return _ORDER[max(0, _ORDER.index(inherent) - steps)]


def rate(likelihood: int, impact: int, control: ControlStrength) -> tuple[Rating, Rating]:
    inh = inherent_rating(likelihood, impact)
    return inh, residual_rating(inh, control)


def overall_rating(residuals: list[Rating]) -> Rating:
    """Overall = the worst residual rating (low if there are no factors)."""
    return max(residuals, key=_ORDER.index) if residuals else Rating.LOW


def backtest_verdict(kupiec_p: float, independence_p: float, alpha: float = 0.05) -> str:
    return "pass" if kupiec_p >= alpha and independence_p >= alpha else "fail"
