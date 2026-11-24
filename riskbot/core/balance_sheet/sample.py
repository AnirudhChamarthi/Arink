"""Deterministic synthetic ~10bn bank for Q2 (``synthetic=True``).

Design (CONTRACT.md section 7): about a quarter of assets in long-dated, low-coupon fixed-rate securities
bought when rates were low (about half HTM, part of them HQLA), loans in four pools that reconcile to the
loan book within 0.5%, deposits of about 70% of total funding with one large, mostly uninsured venture/tech
segment, a short wholesale line, a single small pay-fixed swap, and governance red flags.

Securities' market values are full revaluations of their cash flows at a 4.5% market yield, so they carry
embedded losses against book value. Calibration targets (asserted in the tests):

* base case (+100 bp, slow run, base credit, HTM at cost) passes both constraints;
* +300 bp, fast run, adverse credit, HTM marked to market fails.

``seed`` perturbs balances by at most +-0.5% via ``numpy.random.default_rng(seed)``; the designed pass/fail
behaviour is asserted for the default seed 0.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from riskbot.contract.types import (
    BankBalanceSheet,
    BsAsset,
    DepositSegment,
    LoanPool,
    SwapHedge,
    WholesaleFunding,
)

from .instruments import bond_price

BN = 1_000_000_000.0
MARKET_YIELD = 0.045


def sample_dataset(seed: int = 0) -> BankBalanceSheet:
    rng = np.random.default_rng(seed)

    def j(x: float) -> float:
        """Jitter by at most +-0.5% and round to the nearest thousand."""
        return float(round(x * (1.0 + rng.uniform(-0.005, 0.005)), -3))

    def sec(id_: str, kind: str, book: float, coupon: float, maturity: float, level: str | None) -> BsAsset:
        b = j(book)
        mv = round(b * bond_price(maturity, coupon, MARKET_YIELD) / bond_price(maturity, coupon, coupon), -3)
        return BsAsset(id=id_, kind=kind, book_value=b, market_value=mv, coupon_rate=coupon,
                       maturity_years=maturity, repricing_years=maturity, hqla_level=level)

    cash = j(1.05 * BN)
    loans_fixed = j(2.9 * BN)
    loans_float = j(3.25 * BN)
    assets = [
        BsAsset(id="cash_reserves", kind="cash", book_value=cash, market_value=cash, coupon_rate=0.04,
                maturity_years=0.0, repricing_years=0.0, hqla_level="1"),
        sec("ust_notes_hqla", "hqla_securities", 0.75 * BN, 0.030, 3.0, "1"),
        sec("agency_bonds_hqla", "hqla_securities", 0.30 * BN, 0.025, 5.0, "2a"),
        sec("agency_mbs_afs", "afs_securities", 0.25 * BN, 0.025, 8.0, None),
        sec("ust_bonds_htm", "htm_securities", 0.70 * BN, 0.0300, 10.0, "1"),
        sec("agency_mbs_htm", "htm_securities", 0.45 * BN, 0.0325, 12.0, "2a"),
        sec("municipal_htm", "htm_securities", 0.15 * BN, 0.0350, 15.0, None),
        BsAsset(id="loans_fixed_rate", kind="loans", book_value=loans_fixed, market_value=round(0.95 * loans_fixed, -3),
                coupon_rate=0.042, maturity_years=7.0, repricing_years=7.0),
        BsAsset(id="loans_floating_rate", kind="loans", book_value=loans_float, market_value=loans_float,
                coupon_rate=0.068, maturity_years=4.0, repricing_years=0.25),
        BsAsset(id="premises_and_other", kind="other", book_value=j(0.35 * BN), market_value=j(0.35 * BN),
                coupon_rate=0.0, maturity_years=0.0, repricing_years=0.0),
    ]
    loan_book = loans_fixed + loans_float
    shares = {"residential_mortgage": 0.37, "commercial_real_estate": 0.26, "venture_and_tech_lending": 0.24,
              "consumer": 0.13}
    params = {"residential_mortgage": (0.008, 0.25, 0.15), "commercial_real_estate": (0.020, 0.40, 0.18),
              "venture_and_tech_lending": (0.025, 0.45, 0.20), "consumer": (0.030, 0.70, 0.04)}
    pools = [LoanPool(segment=k, ead=float(round(loan_book * 1.004 * s, -3)), pd=params[k][0], lgd=params[k][1],
                      asset_correlation=params[k][2]) for k, s in shares.items()]
    deposits = [
        DepositSegment(segment="retail", balance=j(2.0 * BN), insured_share=0.90, rate_beta=0.25,
                       runoff_slow=0.03, runoff_fast=0.10, rate=0.010),
        DepositSegment(segment="small_business", balance=j(1.3 * BN), insured_share=0.45, rate_beta=0.40,
                       runoff_slow=0.08, runoff_fast=0.25, rate=0.015),
        DepositSegment(segment="corporate_operating", balance=j(1.0 * BN), insured_share=0.10, rate_beta=0.60,
                       runoff_slow=0.12, runoff_fast=0.40, rate=0.025),
        DepositSegment(segment="venture_tech_clients", balance=j(3.0 * BN), insured_share=0.06, rate_beta=0.70,
                       runoff_slow=0.15, runoff_fast=0.55, rate=0.030),
    ]
    wholesale = [
        WholesaleFunding(id="fhlb_advance_short", amount=j(0.45 * BN), maturity_days=21, rate=0.047),
        WholesaleFunding(id="term_repo", amount=j(0.80 * BN), maturity_days=270, rate=0.046),
    ]
    hedges = [SwapHedge(id="payer_swap_5y", notional=j(0.15 * BN), fixed_rate=0.035, maturity_years=5.0)]
    return BankBalanceSheet(
        name="Synthetic Regional Bank (Q2 sample)",
        as_of=dt.date(2026, 10, 30),
        currency="USD",
        synthetic=True,
        assets=assets,
        loan_pools=pools,
        deposits=deposits,
        wholesale_funding=wholesale,
        hedges=hedges,
        cet1_capital=j(0.85 * BN),
        risk_weighted_assets=j(7.2 * BN),
        policy_rate=0.04,
        governance={
            "cro_vacancy_months": 8,
            "hedges_reduced_last_year": True,
            "deposit_growth_2y": 0.85,
            "uninsured_deposit_limit_set": False,
            "board_risk_committee_meetings_per_year": 4,
            "liquidity_stress_test_frequency": "quarterly",
        },
    )
