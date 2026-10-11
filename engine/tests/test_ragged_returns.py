"""Portfolios whose positions have different history lengths."""

import numpy as np
import pytest

from models.portfolio_utils import returns_matrix
from models.var import historical_var, montecarlo_var, parametric_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _pos(ticker, returns, asset_class=AssetClass.EQUITY):
    return EnrichedPosition(
        ticker=ticker, asset_class=asset_class, quantity=100.0, cost_price=100.0, currency="USD",
        current_price=100.0, returns_252d=list(returns), implied_vol=0.25, risk_free_rate=0.04,
        esg_score=60.0, carbon_intensity=50.0,
    )


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


def test_shorter_history_truncates_to_the_common_most_recent_window():
    rng = np.random.default_rng(0)
    long_ = rng.normal(0, 0.01, 252)
    short = rng.normal(0, 0.01, 90)
    R = returns_matrix(_pf(_pos("L", long_), _pos("S", short)), ["L", "S"])
    assert R.shape == (90, 2)
    np.testing.assert_array_equal(R[:, 0], long_[-90:])  # aligned on the latest days
    np.testing.assert_array_equal(R[:, 1], short)


def test_assets_without_history_are_zero_filled_to_the_common_length():
    rng = np.random.default_rng(1)
    R = returns_matrix(_pf(_pos("A", rng.normal(0, 0.01, 120)), _pos("C", [], AssetClass.CASH)), ["A", "C"])
    assert R.shape == (120, 2)
    assert not R[:, 1].any()


def test_all_empty_histories_fall_back_to_252_zero_rows():
    assert returns_matrix(_pf(_pos("C", [], AssetClass.CASH)), ["C"]).shape == (252, 1)


@pytest.mark.parametrize("method", [parametric_var, historical_var, montecarlo_var])
def test_var_methods_accept_ragged_histories(method):
    rng = np.random.default_rng(2)
    res = method(_pf(_pos("A", rng.normal(0, 0.01, 252)), _pos("B", rng.normal(0, 0.01, 60))), 0.99, 1)
    assert res.var > 0 and np.isfinite(res.var)
