"""Historical VaR contributions are tail-conditional and add up to the portfolio figure."""

import numpy as np
import pytest

from models.var import historical_var
from schemas.contract import AssetClass, EnrichedPortfolio, EnrichedPosition


def _pos(ticker, returns, qty=100.0):
    return EnrichedPosition(
        ticker=ticker, asset_class=AssetClass.EQUITY, quantity=qty, cost_price=100.0, currency="USD",
        current_price=100.0, returns_252d=list(returns), implied_vol=0.25, risk_free_rate=0.04,
        esg_score=60.0, carbon_intensity=50.0,
    )


def _pf(*positions):
    return EnrichedPortfolio(portfolio_name="t", base_currency="USD", positions=list(positions))


def _contrib(res):
    return {c.ticker: c for c in res.contributions}


def test_shares_sum_to_one_and_amounts_sum_to_var():
    rng = np.random.default_rng(0)
    res = historical_var(_pf(_pos("A", rng.normal(0, 0.01, 252)), _pos("B", rng.normal(0, 0.02, 252))), 0.95, 1)
    assert sum(c.pct_of_total for c in res.contributions) == pytest.approx(1.0)
    assert sum(c.var_contribution for c in res.contributions) == pytest.approx(res.var)


def test_the_asset_that_drives_the_tail_dominates_even_when_its_average_return_is_positive():
    # A is steady and slightly positive on average; B is flat except for a handful of crashes.
    rng = np.random.default_rng(1)
    a = rng.normal(0.001, 0.002, 252)
    b = np.zeros(252)
    b[::25] = -0.10  # crashes on ~10 days
    res = historical_var(_pf(_pos("A", a), _pos("B", b)), 0.95, 1)
    c = _contrib(res)
    assert c["B"].pct_of_total > 0.9
    assert c["B"].var_contribution > c["A"].var_contribution


def test_a_hedge_that_gains_in_the_tail_has_a_negative_contribution():
    rng = np.random.default_rng(2)
    a = rng.normal(0, 0.02, 252)
    hedge = -0.5 * a  # moves opposite to A
    res = historical_var(_pf(_pos("A", a), _pos("H", hedge)), 0.95, 1)
    c = _contrib(res)
    assert c["H"].pct_of_total < 0 < c["A"].pct_of_total


def test_multi_day_contributions_still_add_up():
    rng = np.random.default_rng(3)
    res = historical_var(_pf(_pos("A", rng.normal(0, 0.01, 252)), _pos("B", rng.normal(0, 0.01, 252))), 0.95, 5)
    assert sum(c.pct_of_total for c in res.contributions) == pytest.approx(1.0)
