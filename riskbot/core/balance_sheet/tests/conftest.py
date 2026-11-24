from __future__ import annotations

import datetime as dt

import pytest

from riskbot.contract.types import BankBalanceSheet, BsAsset, DepositSegment, LoanPool, SwapHedge, WholesaleFunding
from riskbot.core.balance_sheet import sample_dataset


@pytest.fixture(scope="session")
def bank() -> BankBalanceSheet:
    return sample_dataset()


def tiny_bank(**over) -> BankBalanceSheet:
    """A small bank whose numbers can be checked by hand.

    cash 100; HQLA zero-coupon 5y 200 (level 1); AFS zero-coupon 4y 100; HTM zero-coupon 10y book 300 / MV 250;
    loans 500 floating (repricing 0.5y); one deposit segment 800 (insured 50%, beta 0.5, slow 10%, fast 30%);
    wholesale 50 maturing in 10 days; CET1 60; RWA 600; policy rate 4%.
    """
    kw = dict(
        name="tiny", as_of=dt.date(2026, 10, 30), synthetic=True, policy_rate=0.04,
        assets=[
            BsAsset(id="cash", kind="cash", book_value=100, market_value=100, coupon_rate=0.04, maturity_years=0,
                    repricing_years=0, hqla_level="1"),
            BsAsset(id="hqla", kind="hqla_securities", book_value=200, market_value=200, coupon_rate=0.0,
                    maturity_years=5, repricing_years=5, hqla_level="1"),
            BsAsset(id="afs", kind="afs_securities", book_value=100, market_value=100, coupon_rate=0.0,
                    maturity_years=4, repricing_years=4),
            BsAsset(id="htm", kind="htm_securities", book_value=300, market_value=250, coupon_rate=0.0,
                    maturity_years=10, repricing_years=10),
            BsAsset(id="loans", kind="loans", book_value=500, market_value=500, coupon_rate=0.06, maturity_years=5,
                    repricing_years=0.5),
        ],
        loan_pools=[LoanPool(segment="all", ead=500, pd=0.02, lgd=0.4, asset_correlation=0.15)],
        deposits=[DepositSegment(segment="d", balance=800, insured_share=0.5, rate_beta=0.5, runoff_slow=0.10,
                                 runoff_fast=0.30)],
        wholesale_funding=[WholesaleFunding(id="w", amount=50, maturity_days=10, rate=0.045)],
        hedges=[SwapHedge(id="s", notional=40, fixed_rate=0.04, maturity_years=3)],
        cet1_capital=60, risk_weighted_assets=600,
    )
    kw.update(over)
    return BankBalanceSheet(**kw)


@pytest.fixture
def tiny() -> BankBalanceSheet:
    return tiny_bank()
