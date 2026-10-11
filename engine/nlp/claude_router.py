"""Route NLQ queries to quant models — Claude when configured, keyword fallback otherwise."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from nlp.anthropic_config import anthropic_model
from nlp.prompts import ROUTING_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Step 7 NLQ executor surface.
ALLOWED_NLQ_MODELS = frozenset(
    {"var", "concentration", "sustainability", "greeks", "stress", "garch"}
)


@dataclass
class RoutingInstruction:
    models_to_run: list[str]
    parameters: dict[str, Any]
    topline_metric: str
    explanation_request: str


def route_query(query: str, portfolio_summary: str) -> RoutingInstruction:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            return _route_with_claude(query, portfolio_summary, api_key)
        except Exception as exc:
            logger.warning("Claude routing failed (%s); using keyword fallback.", exc)
    return _route_with_keywords(query)


def _route_with_claude(query: str, portfolio_summary: str, api_key: str) -> RoutingInstruction:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_content = (
        f"Portfolio context:\n{portfolio_summary}\n\nUser query:\n{query.strip()}"
    )
    message = client.messages.create(
        model=anthropic_model(),
        max_tokens=1024,
        system=ROUTING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = message.content[0].text if message.content else ""
    payload = _extract_json(text)
    return _instruction_from_payload(payload)


def _route_with_keywords(query: str) -> RoutingInstruction:
    q = query.lower()
    if any(k in q for k in ("concentration", "largest", "biggest weight", "overweight")):
        return RoutingInstruction(
            models_to_run=["concentration"],
            parameters={},
            topline_metric="Largest single-name portfolio weight",
            explanation_request="Explain concentration risk and whether limits are breached.",
        )
    if any(k in q for k in ("esg", "carbon", "sustain", "climate", "paris")):
        return RoutingInstruction(
            models_to_run=["sustainability"],
            parameters={"sustainability": {"include_carbon_var": True, "run_exclusion_check": True}},
            topline_metric="Portfolio weighted-average ESG score",
            explanation_request="Explain ESG profile, carbon intensity, and exclusion flags.",
        )
    if any(k in q for k in ("greek", "delta", "gamma", "vega", "theta")):
        return RoutingInstruction(
            models_to_run=["greeks"],
            parameters={},
            topline_metric="Portfolio delta",
            explanation_request="Explain portfolio Greeks and directional sensitivities.",
        )
    if any(k in q for k in ("stress", "scenario", "2008", "covid", "shock")):
        scenario = "2008_credit"
        if "covid" in q:
            scenario = "covid_2020"
        elif "rate" in q:
            scenario = "rate_shock_200bps"
        elif "oil" in q:
            scenario = "oil_spike_50pct"
        return RoutingInstruction(
            models_to_run=["stress"],
            parameters={"stress": {"scenario": scenario}},
            topline_metric="Stressed portfolio P&L",
            explanation_request="Explain scenario impact and worst-hit positions.",
        )
    if any(k in q for k in ("garch", "volatility forecast", "vol forecast")):
        ticker = _extract_ticker(q)
        return RoutingInstruction(
            models_to_run=["garch"],
            parameters={"garch": {"ticker": ticker or ""}},
            topline_metric="GARCH conditional volatility",
            explanation_request="Explain GARCH fit and volatility forecast.",
        )
    confidence = 0.99
    m = re.search(r"(\d{2,3})\s*%", q)
    if m:
        confidence = min(0.999, max(0.5, int(m.group(1)) / 100.0))
    horizon = 1
    if "10 day" in q or "10-day" in q:
        horizon = 10
    method = "parametric"
    if "historical" in q:
        method = "historical"
    elif "monte carlo" in q or "montecarlo" in q:
        method = "montecarlo"
    return RoutingInstruction(
        models_to_run=["var"],
        parameters={
            "var": {
                "method": method,
                "confidence": confidence,
                "horizon_days": horizon,
            }
        },
        topline_metric=f"{horizon}-Day {confidence:.0%} VaR ({method.title()})",
        explanation_request="Explain portfolio VaR, key contributors, and limit comparison.",
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _instruction_from_payload(payload: dict[str, Any]) -> RoutingInstruction:
    models = payload.get("models_to_run") or ["var"]
    if isinstance(models, str):
        models = [models]
    allowed = [str(m).lower() for m in models if str(m).lower() in ALLOWED_NLQ_MODELS]
    if not allowed:
        logger.warning(
            "Claude routed to unsupported models %s; defaulting to var.",
            models,
        )
        allowed = ["var"]
    return RoutingInstruction(
        models_to_run=allowed,
        parameters=dict(payload.get("parameters") or {}),
        topline_metric=str(payload.get("topline_metric") or "Portfolio risk metric"),
        explanation_request=str(
            payload.get("explanation_request") or "Explain the result for a risk manager."
        ),
    )


def _extract_ticker(query: str) -> str | None:
    for token in query.upper().replace(",", " ").split():
        cleaned = re.sub(r"[^A-Z0-9.-]", "", token)
        if 1 <= len(cleaned) <= 6 and cleaned.isalpha():
            return cleaned
    return None
