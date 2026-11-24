"""q2.data_quality: hand-computed metrics, findings and the quality label."""

from __future__ import annotations

import pytest

from riskbot.contract import conformance
from riskbot.contract.types import DepositSegment, LoanPool, Severity
from riskbot.core.balance_sheet.data_quality import DataQualityModel

from .conftest import tiny_bank

MODEL = DataQualityModel()


def test_tiny_bank_metrics_by_hand(tiny):
    out = MODEL.run(tiny, {}, 0)
    assert conformance.check_output(MODEL.spec, out) == []
    m = {k: v.value for k, v in out.metrics.items()}
    assert m["loan_reconciliation_gap"] == 0.0
    assert m["uninsured_deposit_share"] == pytest.approx(0.5)
    assert m["largest_segment_share"] == pytest.approx(1.0)
    a = 100 + 200 + 100 + 250 + 500
    assert m["hqla_share"] == pytest.approx(300 / a)
    d_a = (200 * 5 / 1.04 + 100 * 4 / 1.04 + 250 * 10 / 1.04 + 500 * 0.5 / 1.06) / a
    d_l = (800 * 1.0 + 50 * 10 / 365) / 850
    assert m["duration_gap_years"] == pytest.approx(d_a - 850 / a * d_l, rel=1e-10)
    assert m["hedge_ratio"] == pytest.approx(40 / 550)
    assert m["htm_share_of_securities"] == pytest.approx(250 / 550)
    checks = {f.check for f in out.findings}
    assert {"deposit_concentration", "thin_hedging", "large_embedded_loss"} <= checks
    assert out.labels["quality"] == "fair"


def test_sample_findings(bank):
    out = MODEL.run(bank, {}, 0)
    checks = {f.check for f in out.findings}
    assert {"uninsured_share_high", "deposit_concentration", "thin_hedging", "cro_vacancy", "hedges_reduced",
            "rapid_deposit_growth"} <= checks
    assert out.metrics["loan_reconciliation_gap"].value < 0.02
    assert out.labels["quality"] == "fair"


def test_reconciliation_gap_thresholds(tiny):
    def run(ead):
        bank = tiny_bank(loan_pools=[LoanPool(segment="all", ead=ead, pd=0.02, lgd=0.4, asset_correlation=0.1)])
        return MODEL.run(bank, {}, 0)

    warn = run(515.0)  # 3%
    assert warn.metrics["loan_reconciliation_gap"].value == pytest.approx(0.03)
    f = next(f for f in warn.findings if f.check == "loan_reconciliation_gap")
    assert f.severity == Severity.WARNING
    bad = run(400.0)  # 20%: data_quality still runs (only the stress models refuse it)
    assert bad.labels["quality"] == "poor"


def test_good_quality_bank(tiny):
    deposits = [DepositSegment(segment=f"s{i}", balance=200, insured_share=0.9, rate_beta=0.3, runoff_slow=0.02,
                               runoff_fast=0.05) for i in range(4)]
    assets = [a.model_copy(update={"market_value": a.book_value}) for a in tiny.assets]
    hedges = [tiny.hedges[0].model_copy(update={"notional": 400})]
    out = MODEL.run(tiny_bank(deposits=deposits, assets=assets, hedges=hedges), {}, 0)
    assert out.findings == [] and out.labels["quality"] == "good"


def test_unhedged_fixed_rate_book_and_errors(tiny):
    bank = tiny_bank(hedges=[], deposits=[DepositSegment(segment="d", balance=800, insured_share=0.5, rate_beta=0.5,
                                                         runoff_slow=0.3, runoff_fast=0.1)])
    out = MODEL.run(bank, {}, 0)
    checks = {f.check: f.severity for f in out.findings}
    assert checks["unhedged_fixed_rate_securities"] == Severity.WARNING
    assert checks["runoff_order"] == Severity.ERROR
    assert out.labels["quality"] == "poor"
    assert out.metrics["hedge_ratio"].value == 0.0
