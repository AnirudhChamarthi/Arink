"""The EWMA fallback must be a faithful GARCH(1,1) special case and must not fail silently."""

import logging
import math

import numpy as np
import pytest
from scipy import stats

import models.garch as garch
from models.garch import _ewma_fallback, run_garch
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _pf(returns):
    pos = EnrichedPosition(
        ticker="G", asset_class=AssetClass.EQUITY, quantity=1.0, cost_price=100.0, currency="USD",
        current_price=100.0, returns_252d=list(returns), implied_vol=0.25, risk_free_rate=0.04,
        esg_score=60.0, carbon_intensity=50.0,
    )
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=[pos])


def _returns():
    return np.random.default_rng(3).normal(0, 0.01, 252)


def test_fallback_reports_ewma_as_a_garch_special_case():
    res = _ewma_fallback("G", _returns())
    assert res.omega == 0.0
    assert res.alpha == pytest.approx(0.06)
    assert res.beta_param == pytest.approx(0.94)
    assert res.alpha + res.beta_param == pytest.approx(1.0)
    assert res.arma_order is not None  # marks the fallback


def test_fallback_forecast_is_flat_and_consistent_with_var():
    r = _returns()
    res = _ewma_fallback("G", r)
    assert len(res.vol_forecast_series) == 10
    assert len(set(res.vol_forecast_series)) == 1
    assert res.vol_forecast_10d == res.vol_forecast_series[0]
    assert res.conditional_var_1d == pytest.approx(res.vol_forecast_series[0] * stats.norm.ppf(0.99))


def test_fallback_volatility_matches_a_hand_computed_ewma():
    r = np.array([0.01, -0.02, 0.015] * 20)
    var = float(np.var(r))
    for x in r:
        var = 0.94 * var + 0.06 * x * x
    assert _ewma_fallback("G", r).vol_forecast_series[0] == pytest.approx(math.sqrt(var))


def test_fallback_log_likelihood_is_real():
    res = _ewma_fallback("G", _returns())
    assert res.log_likelihood != 0.0
    assert res.aic == pytest.approx(-2 * res.log_likelihood)
    # near N(0, 0.01^2): per-observation LL is about -0.5*(ln(2*pi) + 2*ln(0.01) + 1) = 3.38
    assert res.log_likelihood / 252 == pytest.approx(3.38, abs=0.3)


def test_failed_fit_falls_back_and_logs_a_warning(monkeypatch, caplog):
    def boom(ticker, returns):
        raise RuntimeError("optimizer did not converge (flag 4)")

    monkeypatch.setattr(garch, "_fit_arch_garch", boom)
    with caplog.at_level(logging.WARNING, logger="models.garch"):
        res = run_garch(_pf(_returns()), "G")
    assert res.arma_order is not None
    assert "did not converge" in caplog.text
