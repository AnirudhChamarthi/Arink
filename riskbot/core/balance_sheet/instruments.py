"""Instrument-level mathematics: bond cash flows, duration, convexity, Vasicek stressed PD, fire sales.

Everything here is a pure function of floats so it can be tested against independent oracles.

Bond conventions
----------------
A bullet bond with annual coupon rate ``c`` (per unit face) and time to maturity ``T`` years pays
``n = ceil(T)`` cash flows at times ``t_i = T - (n - i)``, ``i = 1..n``: a full coupon ``c`` at each date and
the face value 1 at ``T``. With annual compounding at yield ``y`` (discount factor ``v = 1/(1+y)``):

.. math::

    P(y) = \\sum_i CF_i v^{t_i}, \\qquad
    D_{mac} = \\frac{1}{P}\\sum_i t_i CF_i v^{t_i}, \\qquad
    D_{mod} = \\frac{D_{mac}}{1+y}, \\qquad
    C = \\frac{1}{P}\\sum_i t_i (t_i + 1) CF_i v^{t_i + 2}

so that :math:`\\Delta P / P \\approx -D_{mod}\\Delta y + \\tfrac12 C \\Delta y^2`. For integer ``T`` and
``y = c`` the bond is priced at par and :math:`D_{mac} = \\frac{1+y}{y}\\left(1 - (1+y)^{-T}\\right)`;
for a zero-coupon bond :math:`D_{mod} = T/(1+y)` and :math:`C = T(T+1)/(1+y)^2`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.stats import norm

# ------------------------------------------------------------------------------------------------
# Bonds
# ------------------------------------------------------------------------------------------------


def bond_cash_flows(maturity: float, coupon: float) -> list[tuple[float, float]]:
    """(time, cash flow) pairs per unit face for an annual-coupon bullet bond; empty for maturity 0."""
    if maturity <= 0:
        return []
    n = max(1, math.ceil(maturity - 1e-9))
    flows = []
    for i in range(1, n + 1):
        t = maturity - (n - i)
        flows.append((t, coupon + (1.0 if i == n else 0.0)))
    return flows


def bond_price(maturity: float, coupon: float, y: float) -> float:
    """Full revaluation: present value of the cash flows at annually compounded yield ``y``."""
    if maturity <= 0:
        return 1.0
    return sum(cf * (1.0 + y) ** (-t) for t, cf in bond_cash_flows(maturity, coupon))


def bond_risk(maturity: float, coupon: float, y: float) -> tuple[float, float, float]:
    """(Macaulay duration, modified duration, convexity) from the cash-flow schedule at yield ``y``.

    A zero maturity (cash, overnight) has zero duration and convexity.
    """
    if maturity <= 0:
        return 0.0, 0.0, 0.0
    flows = bond_cash_flows(maturity, coupon)
    v = 1.0 / (1.0 + y)
    p = sum(cf * v**t for t, cf in flows)
    mac = sum(t * cf * v**t for t, cf in flows) / p
    conv = sum(t * (t + 1) * cf * v ** (t + 2) for t, cf in flows) / p
    return mac, mac / (1.0 + y), conv


def zero_coupon_convexity_for_duration(modified_duration: float, y: float) -> float:
    """Convexity of the zero-coupon bond with the given modified duration: :math:`D^2 + D/(1+y)`.

    Used when a modified duration is supplied without a convexity (from :math:`T = D(1+y)` and
    :math:`C = T(T+1)/(1+y)^2`).
    """
    d = modified_duration
    return d * d + d / (1.0 + y)


def value_change(market_value: float, modified_duration: float, convexity: float, dy: float) -> float:
    """Second-order Taylor approximation :math:`\\Delta V = MV(-D\\Delta y + \\tfrac12 C\\Delta y^2)`."""
    return market_value * (-modified_duration * dy + 0.5 * convexity * dy * dy)


# ------------------------------------------------------------------------------------------------
# Credit: Vasicek single-factor stressed PD
# ------------------------------------------------------------------------------------------------


def vasicek_pd(pd: float, rho: float, q: float) -> float:
    """Stressed (conditional) PD at the ``q`` quantile of the systematic factor (Vasicek, 2002):

    .. math:: PD_s = \\Phi\\left(\\frac{\\Phi^{-1}(PD) + \\sqrt{\\rho}\\,\\Phi^{-1}(q)}{\\sqrt{1-\\rho}}\\right)

    This is the ``q`` quantile of the default rate of an infinitely granular homogeneous pool whose
    obligors default when :math:`\\sqrt{\\rho}Z + \\sqrt{1-\\rho}\\varepsilon_i < \\Phi^{-1}(PD)`.
    """
    if not (0 < pd < 1 and 0 < rho < 1 and 0 < q < 1):
        raise ValueError("pd, rho and q must lie in (0, 1)")
    return float(norm.cdf((norm.ppf(pd) + math.sqrt(rho) * norm.ppf(q)) / math.sqrt(1.0 - rho)))


# ------------------------------------------------------------------------------------------------
# Fire sales: proceeds(s) = s * S * exp(-lambda * s) = need
# ------------------------------------------------------------------------------------------------


@dataclass
class FireSale:
    """Solution of the fire-sale fixed point.

    ``share`` is the fraction ``s`` of the saleable pool (market value ``S``) sold, ``price`` the price factor
    ``exp(-lambda s)``, ``proceeds = s S price`` and ``shortfall`` the part of the need that cannot be met even
    by selling everything. ``iterations`` holds ``(k, s_k, proceeds(s_k))``.
    """

    share: float
    price: float
    proceeds: float
    shortfall: float
    converged: bool
    method: str
    iterations: list[tuple[int, float, float]] = field(default_factory=list)


def fire_sale_proceeds(share: float, pool: float, impact: float) -> float:
    return share * pool * math.exp(-impact * share)


def solve_fire_sale(need: float, pool: float, impact: float, *, tol: float = 1e-12, max_iter: int = 200) -> FireSale:
    """Solve :math:`s S e^{-\\lambda s} = N` for the share sold ``s`` in [0, 1].

    Fixed-point iteration :math:`s_{k+1} = g(s_k) = \\frac{N}{S} e^{\\lambda s_k}`, :math:`s_0 = 0`. ``g`` is
    increasing and convex with :math:`g'(s) = \\lambda g(s)`, so at the fixed point :math:`g'(s^*) = \\lambda s^*`;
    for :math:`\\lambda \\le 1` and :math:`s^* < 1` this is a contraction near :math:`s^*` and the iterates
    increase monotonically to the smallest root. Proceeds are increasing in ``s`` on [0, 1/lambda] ⊇ [0, 1]
    (lambda <= 1), so the maximum is :math:`S e^{-\\lambda}`: a larger need sells everything and leaves a
    shortfall. If iteration fails to converge in ``max_iter`` steps (only when :math:`\\lambda s^* \\to 1`),
    bisection on [s_k, 1] finishes the job and ``method`` says so.
    """
    if need <= 0 or pool <= 0:
        return FireSale(0.0, 1.0, 0.0, max(0.0, need), True, "none", [])
    max_proceeds = fire_sale_proceeds(1.0, pool, impact)
    if need >= max_proceeds:
        return FireSale(1.0, math.exp(-impact), max_proceeds, need - max_proceeds, True, "sell_all", [])
    s = 0.0
    its: list[tuple[int, float, float]] = [(0, s, 0.0)]
    for k in range(1, max_iter + 1):
        s_new = min(1.0, need / pool * math.exp(impact * s))
        its.append((k, s_new, fire_sale_proceeds(s_new, pool, impact)))
        if abs(s_new - s) <= tol * max(1.0, s_new):
            s = s_new
            return FireSale(s, math.exp(-impact * s), fire_sale_proceeds(s, pool, impact), 0.0, True,
                            "fixed_point", its)
        s = s_new
    lo, hi = its[-2][1], 1.0  # proceeds(lo) < need <= proceeds(1)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if fire_sale_proceeds(mid, pool, impact) < need:
            lo = mid
        else:
            hi = mid
        if hi - lo <= tol:
            break
    s = hi
    return FireSale(s, math.exp(-impact * s), fire_sale_proceeds(s, pool, impact), 0.0, True, "bisection", its)
