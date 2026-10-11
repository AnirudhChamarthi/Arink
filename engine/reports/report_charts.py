"""Matplotlib charts embedded in Riskbot Excel reports."""

from __future__ import annotations

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np

from models.portfolio_utils import returns_matrix, weight_vector
from models.var import montecarlo_var
from schemas.contract import EnrichedPortfolio, VarMethod

_MAX_BAR_ITEMS = 12
_MAX_CHARTS_PER_REPORT = 8
_CHART_DPI = 120
_CHART_WIDTH = 8.0
_CHART_HEIGHT = 4.0


def build_nlq_charts(
    *,
    models_used: list[str],
    detail_rows: list[dict[str, Any]],
    portfolio: EnrichedPortfolio | None,
) -> list[tuple[str, bytes]]:
    if not models_used:
        return []
    primary = models_used[0].split(":")[0]
    builders = {
        "var": _var_charts,
        "concentration": _concentration_charts,
        "sustainability": _sustainability_charts,
        "greeks": _greeks_charts,
        "stress": _stress_charts,
        "garch": _garch_charts,
    }
    builder = builders.get(primary)
    if builder is None:
        return []
    return builder(portfolio, detail_rows, models_used)[:_MAX_CHARTS_PER_REPORT]


def build_full_report_charts(
    *,
    portfolio: EnrichedPortfolio,
    var_result,
    greeks_result,
    sustainability_result,
    stress_result,
) -> list[tuple[str, bytes]]:
    """Charts for the master full-risk Excel workbook."""
    charts: list[tuple[str, bytes]] = []
    charts.extend(_var_charts(portfolio, [], [f"var:{var_result.method.value}"]))
    if var_result.contributions:
        charts.append(
            _horizontal_bar_chart(
                "VaR contribution by position (%)",
                [c.ticker for c in var_result.contributions[:_MAX_BAR_ITEMS]],
                [c.pct_of_total * 100.0 for c in var_result.contributions[:_MAX_BAR_ITEMS]],
                "Ticker",
                "% of portfolio VaR",
            )
        )
    if greeks_result.positions:
        charts.append(
            _horizontal_bar_chart(
                "Position delta",
                [p.ticker for p in greeks_result.positions[:_MAX_BAR_ITEMS]],
                [p.delta for p in greeks_result.positions[:_MAX_BAR_ITEMS]],
                "Ticker",
                "Delta",
            )
        )
    if sustainability_result.per_position_esg:
        charts.append(
            _horizontal_bar_chart(
                "ESG score by position",
                [r.ticker for r in sustainability_result.per_position_esg[:_MAX_BAR_ITEMS]],
                [r.esg_score for r in sustainability_result.per_position_esg[:_MAX_BAR_ITEMS]],
                "Ticker",
                "ESG (0–100)",
            )
        )
    if stress_result.positions:
        worst = sorted(stress_result.positions, key=lambda p: p.pnl_impact)[:_MAX_BAR_ITEMS]
        charts.append(
            _horizontal_bar_chart(
                f"Stress P&L — {stress_result.scenario}",
                [p.ticker for p in worst],
                [p.pct_impact * 100.0 for p in worst],
                "Ticker",
                "% of portfolio MV",
            )
        )
    return charts[:_MAX_CHARTS_PER_REPORT]


def _var_charts(
    portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    models_used: list[str],
) -> list[tuple[str, bytes]]:
    charts: list[tuple[str, bytes]] = []
    method = VarMethod.PARAMETRIC
    if models_used and ":" in models_used[0]:
        try:
            method = VarMethod(models_used[0].split(":", 1)[1])
        except ValueError:
            pass

    if portfolio and portfolio.positions:
        tickers, weights = weight_vector(portfolio)
        if tickers:
            R = returns_matrix(portfolio, tickers)
            port_returns = R @ weights
            charts.append(_returns_histogram(port_returns, method))

    if detail_rows and "pct_of_total" in detail_rows[0]:
        rows = sorted(detail_rows, key=lambda r: r.get("pct_of_total", 0), reverse=True)[
            :_MAX_BAR_ITEMS
        ]
        charts.append(
            _horizontal_bar_chart(
                "VaR contribution by position (%)",
                [str(r["ticker"]) for r in rows],
                [float(r["pct_of_total"]) * 100.0 for r in rows],
                "Ticker",
                "% of total VaR",
            )
        )

    if portfolio and method == VarMethod.MONTECARLO:
        result = montecarlo_var(portfolio, 0.99, 1, n_sims=5000)
        rng = np.random.default_rng(42)
        tickers, weights = weight_vector(portfolio)
        R = returns_matrix(portfolio, tickers)
        cov = np.cov(R, rowvar=False)
        if cov.ndim == 0:
            cov = np.array([[float(cov)]])
        mean = np.mean(R, axis=0)
        sims = rng.multivariate_normal(mean, cov, size=5000) @ weights
        charts.append(_loss_histogram(-sims, result.var, "Monte Carlo loss distribution"))

    return charts


def _concentration_charts(
    portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    _models_used: list[str],
) -> list[tuple[str, bytes]]:
    if not detail_rows:
        return []
    rows = sorted(detail_rows, key=lambda r: r.get("weight_pct", 0), reverse=True)[:_MAX_BAR_ITEMS]
    return [
        _horizontal_bar_chart(
            "Portfolio weights (%)",
            [str(r["ticker"]) for r in rows],
            [float(r["weight_pct"]) for r in rows],
            "Ticker",
            "Weight %",
        )
    ]


def _sustainability_charts(
    _portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    _models_used: list[str],
) -> list[tuple[str, bytes]]:
    if not detail_rows:
        return []
    rows = detail_rows[:_MAX_BAR_ITEMS]
    return [
        _horizontal_bar_chart(
            "ESG score by position",
            [str(r["ticker"]) for r in rows],
            [float(r["esg_score"]) for r in rows],
            "Ticker",
            "ESG (0–100)",
        )
    ]


def _greeks_charts(
    _portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    _models_used: list[str],
) -> list[tuple[str, bytes]]:
    if not detail_rows:
        return []
    rows = sorted(detail_rows, key=lambda r: abs(float(r.get("delta", 0))), reverse=True)[
        :_MAX_BAR_ITEMS
    ]
    return [
        _horizontal_bar_chart(
            "Position delta",
            [str(r["ticker"]) for r in rows],
            [float(r["delta"]) for r in rows],
            "Ticker",
            "Delta",
        )
    ]


def _stress_charts(
    _portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    models_used: list[str],
) -> list[tuple[str, bytes]]:
    if not detail_rows:
        return []
    scenario = models_used[0].split(":", 1)[1] if models_used else "stress"
    rows = sorted(detail_rows, key=lambda r: r.get("pnl_impact", 0))[:_MAX_BAR_ITEMS]
    return [
        _horizontal_bar_chart(
            f"Stress P&L impact — {scenario}",
            [str(r["ticker"]) for r in rows],
            [float(r["pct_impact"]) for r in rows],
            "Ticker",
            "% of portfolio MV",
        )
    ]


def _garch_charts(
    _portfolio: EnrichedPortfolio | None,
    detail_rows: list[dict[str, Any]],
    _models_used: list[str],
) -> list[tuple[str, bytes]]:
    if not detail_rows or "vol" not in detail_rows[0]:
        return []
    days = [int(r["day"]) for r in detail_rows]
    vols = [float(r["vol"]) * 100.0 for r in detail_rows]
    return [_line_chart("GARCH volatility forecast (%)", days, vols, "Day", "Vol %")]


def _returns_histogram(port_returns: np.ndarray, method: VarMethod) -> tuple[str, bytes]:
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    ax.hist(port_returns * 100.0, bins=30, color="#2563eb", alpha=0.85, edgecolor="white")
    var_line = float(np.quantile(-port_returns, 0.99)) * 100.0
    ax.axvline(-var_line, color="#dc2626", linestyle="--", linewidth=2, label=f"99% loss ≈ {var_line:.2f}%")
    ax.set_title(f"Portfolio daily returns ({method.value} context)")
    ax.set_xlabel("Return (%)")
    ax.set_ylabel("Frequency")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    return "Portfolio returns distribution", _fig_to_png(fig)


def _loss_histogram(losses: np.ndarray, var_decimal: float, title: str) -> tuple[str, bytes]:
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    ax.hist(losses * 100.0, bins=40, color="#7c3aed", alpha=0.85, edgecolor="white")
    ax.axvline(var_decimal * 100.0, color="#dc2626", linestyle="--", linewidth=2, label="VaR (99%)")
    ax.set_title(title)
    ax.set_xlabel("Loss (%)")
    ax.set_ylabel("Frequency")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    return title, _fig_to_png(fig)


def _horizontal_bar_chart(
    title: str,
    labels: list[str],
    values: list[float],
    xlabel: str,
    ylabel: str,
) -> tuple[str, bytes]:
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, max(3.0, 0.35 * len(labels) + 1.5)))
    y_pos = np.arange(len(labels))
    ax.barh(y_pos, values, color="#0d9488", alpha=0.9)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="x", alpha=0.3)
    return title, _fig_to_png(fig)


def _line_chart(
    title: str,
    xs: list[int],
    ys: list[float],
    xlabel: str,
    ylabel: str,
) -> tuple[str, bytes]:
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    ax.plot(xs, ys, color="#ea580c", marker="o", linewidth=2, markersize=4)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    return title, _fig_to_png(fig)


def _fig_to_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
