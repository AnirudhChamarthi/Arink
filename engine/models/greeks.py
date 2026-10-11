"""Portfolio Greeks — Black-Scholes for options, synthetic finite-difference for equities."""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

from models.portfolio_utils import position_signed_value
from schemas.contract import (
    EnrichedPortfolio,
    EnrichedPosition,
    GreeksMethod,
    PortfolioGreeks,
    PositionGreeks,
)


def run_greeks(portfolio: EnrichedPortfolio) -> PortfolioGreeks:
    positions: list[PositionGreeks] = []
    for pos in portfolio.positions:
        positions.append(_position_greeks(pos))

    return PortfolioGreeks(
        positions=positions,
        portfolio_delta=sum(p.delta for p in positions),
        portfolio_gamma=sum(p.gamma for p in positions),
        portfolio_vega=sum(p.vega for p in positions),
        portfolio_theta=sum(p.theta for p in positions),
        portfolio_rho=sum(p.rho for p in positions),
    )


def _position_greeks(pos: EnrichedPosition) -> PositionGreeks:
    if pos.has_options and pos.options_chain and pos.options_chain.strikes:
        return _options_greeks(pos)
    return _synthetic_equity_greeks(pos)


def _options_greeks(pos: EnrichedPosition) -> PositionGreeks:
    chain = pos.options_chain
    assert chain is not None
    spot = pos.current_price
    strike = min(chain.strikes, key=lambda s: abs(s.strike - spot))
    T = max((strike.expiry.toordinal() - __import__("datetime").date.today().toordinal()) / 365.0, 1 / 365)
    sigma = max(strike.call_iv or pos.implied_vol, 1e-4)
    r = pos.risk_free_rate
    g = _black_scholes_greeks(spot, strike.strike, T, r, sigma, "c")
    scale = pos.quantity
    return PositionGreeks(
        ticker=pos.ticker,
        delta=g["delta"] * scale,
        gamma=g["gamma"] * scale,
        vega=g["vega"] * scale,
        theta=g["theta"] * scale,
        rho=g["rho"] * scale,
        greeks_method=GreeksMethod.BLACK_SCHOLES,
    )


def _synthetic_equity_greeks(pos: EnrichedPosition) -> PositionGreeks:
    """Greeks for plain (non-option) positions, which are linear in the underlying.

    * ``delta`` is the beta-adjusted share delta ``quantity * beta`` (1.0 when beta is unknown).
    * ``gamma`` is taken by finite difference of the position value; it is zero because the
      value is linear in spot.
    * ``vega``, ``theta`` and ``rho`` are zero: a share has no volatility exposure, no time
      decay, and no explicit interest-rate term. (They used to be filled with option-style
      formulas, e.g. a theta of about -$79 per day on a $10k stock position.)
    """
    q = pos.quantity
    s = max(pos.current_price, 1e-6)
    beta = pos.beta if pos.beta is not None else 1.0

    delta = q * beta
    d_s = s * 0.01  # 1% spot bump
    gamma = (q * (s + d_s) - 2 * q * s + q * (s - d_s)) / (d_s**2)

    if pos.asset_class.value == "Cash":
        return PositionGreeks(
            ticker=pos.ticker,
            delta=0.0,
            gamma=0.0,
            vega=0.0,
            theta=0.0,
            rho=position_signed_value(pos) * 0.0001,
            greeks_method=GreeksMethod.SYNTHETIC_FINITE_DIFFERENCE,
        )

    return PositionGreeks(
        ticker=pos.ticker,
        delta=delta,
        gamma=gamma,
        vega=0.0,
        theta=0.0,
        rho=0.0,
        greeks_method=GreeksMethod.SYNTHETIC_FINITE_DIFFERENCE,
    )


def _black_scholes_greeks(
    spot: float,
    strike: float,
    T: float,
    r: float,
    sigma: float,
    flag: str,
) -> dict[str, float]:
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}

    sqrt_t = math.sqrt(T)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf_d1 = norm.pdf(d1)

    if flag == "c":
        delta = norm.cdf(d1)
        theta = (
            -spot * pdf_d1 * sigma / (2 * sqrt_t)
            - r * strike * math.exp(-r * T) * norm.cdf(d2)
        ) / 365.0
        rho = strike * T * math.exp(-r * T) * norm.cdf(d2) * 0.01
    else:
        delta = norm.cdf(d1) - 1.0
        theta = (
            -spot * pdf_d1 * sigma / (2 * sqrt_t)
            + r * strike * math.exp(-r * T) * norm.cdf(-d2)
        ) / 365.0
        rho = -strike * T * math.exp(-r * T) * norm.cdf(-d2) * 0.01

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t * 0.01

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
    }
