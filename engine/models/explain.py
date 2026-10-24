"""Step-by-step working for the VaR and stress models.

Each ``explain_*`` function recomputes the result from the raw inputs, one documented step at a
time, and returns a ``Trace``. The final numbers are checked against the production models in
the tests, so a trace can never drift from the figure the engine reports.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from models.portfolio_utils import gross_exposure, position_signed_value, returns_matrix
from models.stress import _shock_for_position, _validate_shocks
from models.trace import Trace, TraceStep, input_hash, make_trace_id
from schemas.contract import EnrichedPortfolio, StressScenario


def _portfolio_payload(portfolio: EnrichedPortfolio) -> list[dict]:
    return [
        {
            "ticker": p.ticker,
            "asset_class": p.asset_class.value,
            "sector": p.sector,
            "quantity": p.quantity,
            "current_price": p.current_price,
            "returns": list(p.returns_252d),
        }
        for p in portfolio.positions
    ]


def explain_parametric_var(portfolio: EnrichedPortfolio, confidence: float, horizon_days: int) -> Trace:
    """Variance-covariance (normal) VaR and expected shortfall, with every step shown."""
    model = "parametric_var"
    digest = input_hash(
        {"model": model, "portfolio": _portfolio_payload(portfolio), "confidence": confidence, "horizon": horizon_days}
    )
    assumptions = [
        "Daily returns are jointly normal with the sample covariance of the return window.",
        "Returns are independent over time, so h-day volatility is daily volatility times sqrt(h).",
        "Weights are signed market value divided by gross exposure (a short has a negative weight).",
        "Mean return is ignored (zero-drift VaR).",
    ]
    inputs = {"confidence": confidence, "horizon_days": horizon_days, "n_positions": len(portfolio.positions)}

    tickers = [p.ticker.upper() for p in portfolio.positions]
    if not tickers:
        return Trace(
            trace_id=make_trace_id(model, digest), model=model, inputs=inputs, assumptions=assumptions,
            steps=[], result={"var": 0.0, "cvar": 0.0, "var_amount": 0.0}, input_hash=digest,
            warnings=["Portfolio has no positions; VaR is zero."],
        )

    warnings: list[str] = []
    values = np.array([position_signed_value(p) for p in portfolio.positions])
    gross = float(np.abs(values).sum())
    if gross > 0:
        weights = values / gross
    else:
        weights = np.ones(len(values)) / len(values)
        warnings.append("Gross exposure is zero; equal weights were used.")

    steps: list[TraceStep] = []
    steps.append(TraceStep(
        id="weights", title="Weights from signed market values",
        formula=r"G=\sum_i |MV_i|,\qquad w_i=\frac{MV_i}{G}",
        substitution=f"G = {gross:,.2f}",
        value=gross, unit="gross exposure",
        table=[{"ticker": t, "market_value": float(v), "weight": float(w)}
               for t, v, w in zip(tickers, values, weights)],
    ))

    R = returns_matrix(portfolio, tickers)
    n_days = R.shape[0]
    if n_days < 2:
        raise ValueError("Need at least 2 return observations for a covariance estimate.")
    steps.append(TraceStep(
        id="window", title="Return window",
        formula=r"R\in\mathbb{R}^{n\times k}",
        substitution=f"n = {n_days} days, k = {len(tickers)} assets (aligned on the most recent days)",
        value=float(n_days), unit="days",
    ))

    cov = np.atleast_2d(np.cov(R, rowvar=False))
    vols = np.sqrt(np.diag(cov))
    steps.append(TraceStep(
        id="covariance", title="Sample covariance of daily returns",
        formula=r"\Sigma_{ij}=\frac{1}{n-1}\sum_t (r_{ti}-\bar r_i)(r_{tj}-\bar r_j)",
        substitution=f"divisor n-1 = {n_days - 1}",
        table=[{"ticker": t, "daily_vol": float(v)} for t, v in zip(tickers, vols)],
        note="Per-asset daily volatility is sqrt of the diagonal; the full matrix is not listed.",
    ))

    marginal = cov @ weights
    port_var = float(weights @ marginal)
    port_vol = math.sqrt(max(port_var, 0.0))
    steps.append(TraceStep(
        id="portfolio_variance", title="Portfolio daily variance and volatility",
        formula=r"\sigma_p^2=w^\top\Sigma w,\qquad \sigma_p=\sqrt{\sigma_p^2}",
        substitution=f"sigma_p^2 = {port_var:.6e}, sigma_p = {port_vol:.6f}",
        value=port_vol, unit="daily volatility (fraction of gross)",
    ))

    z = float(stats.norm.ppf(confidence))
    steps.append(TraceStep(
        id="quantile", title="Normal quantile",
        formula=r"z_c=\Phi^{-1}(c)", substitution=f"c = {confidence}, z = {z:.6f}", value=z,
    ))

    scale = math.sqrt(horizon_days)
    steps.append(TraceStep(
        id="horizon", title="Square-root-of-time scaling",
        formula=r"\sigma_{p,h}=\sigma_p\sqrt{h}",
        substitution=f"h = {horizon_days}, sqrt(h) = {scale:.6f}, sigma_p,h = {port_vol * scale:.6f}",
        value=port_vol * scale, unit="h-day volatility",
    ))

    var = z * port_vol * scale
    steps.append(TraceStep(
        id="var", title="Value at Risk",
        formula=r"\mathrm{VaR}_{c,h}=z_c\,\sigma_p\sqrt{h}",
        substitution=f"{z:.6f} × {port_vol:.6f} × {scale:.6f}", value=var, unit="fraction of gross",
    ))

    cvar = port_vol * scale * float(stats.norm.pdf(z)) / (1.0 - confidence)
    steps.append(TraceStep(
        id="expected_shortfall", title="Expected shortfall (normal)",
        formula=r"\mathrm{ES}_{c,h}=\sigma_p\sqrt{h}\,\frac{\varphi(z_c)}{1-c}",
        substitution=f"{port_vol * scale:.6f} × {float(stats.norm.pdf(z)):.6f} / {1.0 - confidence:.6f}",
        value=cvar, unit="fraction of gross",
    ))

    component = weights * marginal
    total_component = float(component.sum())
    shares = component / total_component if total_component > 1e-12 else np.zeros(len(tickers))
    steps.append(TraceStep(
        id="contributions", title="Component contribution to VaR",
        formula=r"\mathrm{share}_i=\frac{w_i(\Sigma w)_i}{w^\top\Sigma w},\qquad \mathrm{VaR}_i=\mathrm{share}_i\cdot\mathrm{VaR}",
        substitution=f"sum of shares = {float(shares.sum()):.6f}",
        table=[{"ticker": t, "share": float(s), "var_contribution": float(s * var)}
               for t, s in zip(tickers, shares)],
        note="Shares sum to 1; a negative share is a diversifier.",
    ))

    steps.append(TraceStep(
        id="var_amount", title="VaR in currency",
        formula=r"\mathrm{VaR}_{\$}=\mathrm{VaR}\times G",
        substitution=f"{var:.6f} × {gross:,.2f}", value=var * gross, unit="currency",
    ))

    return Trace(
        trace_id=make_trace_id(model, digest), model=model, inputs=inputs, assumptions=assumptions,
        steps=steps, result={"var": var, "cvar": cvar, "var_amount": var * gross},
        input_hash=digest, warnings=warnings,
    )


def explain_stress(
    portfolio: EnrichedPortfolio,
    scenario: StressScenario,
    custom_shocks: dict[str, float] | None = None,
) -> Trace:
    """Scenario stress P&L with the shock lookup for every position shown."""
    from models.stress import _load_scenarios  # local import keeps the catalogue path in one place

    model = "stress"
    if scenario == StressScenario.CUSTOM:
        shocks = dict(custom_shocks or {})
        if not shocks:
            raise ValueError("custom scenario requires custom_shocks.")
        name = "custom"
    else:
        entry = _load_scenarios().get(scenario.value)
        if entry is None:
            raise ValueError(f"Unknown stress scenario: {scenario.value}")
        shocks = dict(entry.get("shocks") or {})
        name = scenario.value
    _validate_shocks(shocks)

    digest = input_hash({"model": model, "portfolio": _portfolio_payload(portfolio), "scenario": name, "shocks": shocks})
    assumptions = [
        "A position's shock is its sector shock if listed, otherwise its asset-class shock, otherwise 0.",
        "P&L = signed market value × shock, so a short gains when its shock is negative.",
        "Shocks are instantaneous; there is no second-round or liquidity effect.",
    ]

    gross = gross_exposure(portfolio)
    denom = gross or 1.0
    steps: list[TraceStep] = [TraceStep(
        id="shocks", title=f"Scenario shocks ({name})", formula=r"s_k",
        substitution=", ".join(f"{k}: {v:+.2%}" for k, v in sorted(shocks.items())),
        table=[{"key": k, "shock": float(v)} for k, v in sorted(shocks.items())],
    )]

    rows = []
    total = 0.0
    for pos in portfolio.positions:
        mv = position_signed_value(pos)
        shock = _shock_for_position(pos, shocks)
        sector = (pos.sector or "").strip()
        source = "sector" if sector and sector in shocks else ("asset class" if pos.asset_class.value in shocks else "none")
        pnl = mv * shock
        total += pnl
        rows.append({"ticker": pos.ticker, "market_value": mv, "shock_source": source, "shock": shock, "pnl": pnl})
    steps.append(TraceStep(
        id="position_pnl", title="Position P&L",
        formula=r"\mathrm{P\&L}_i=MV_i\cdot s_{k(i)}",
        substitution=f"{len(rows)} positions", table=rows,
    ))
    steps.append(TraceStep(
        id="portfolio_pnl", title="Portfolio P&L",
        formula=r"\mathrm{P\&L}=\sum_i \mathrm{P\&L}_i", substitution=f"sum = {total:,.2f}", value=total, unit="currency",
    ))
    pct = total / denom
    steps.append(TraceStep(
        id="portfolio_pct", title="As a fraction of gross exposure",
        formula=r"\frac{\mathrm{P\&L}}{G}", substitution=f"{total:,.2f} / {denom:,.2f}", value=pct, unit="fraction of gross",
    ))
    return Trace(
        trace_id=make_trace_id(model, digest), model=model,
        inputs={"scenario": name, "n_positions": len(portfolio.positions)},
        assumptions=assumptions, steps=steps, result={"portfolio_pnl": total, "portfolio_pct": pct},
        input_hash=digest,
    )
