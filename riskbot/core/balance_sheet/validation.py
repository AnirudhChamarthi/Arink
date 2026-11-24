"""Input checks shared by the Q2 models: dataset kind, finiteness, limits and internal consistency."""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from riskbot.contract import catalog
from riskbot.contract.errors import LimitExceeded, ValidationFailed
from riskbot.contract.types import BankBalanceSheet

# Above this loan reconciliation gap the credit view cannot be trusted for a stress calculation.
MAX_RECONCILIATION_GAP_FOR_STRESS = 0.25


def coerce_balance_sheet(dataset: Any, model_id: str) -> BankBalanceSheet:
    """Return ``dataset`` as a ``BankBalanceSheet`` or raise ``ValidationFailed`` (wrong kind / invalid)."""
    if isinstance(dataset, BankBalanceSheet):
        return dataset
    if isinstance(dataset, dict):
        if dataset.get("kind", "balance_sheet") != "balance_sheet":
            raise ValidationFailed(f"{model_id} needs a balance_sheet dataset, got {dataset.get('kind')!r}",
                                   model_id=model_id)
        try:
            return BankBalanceSheet.model_validate(dataset)
        except ValidationError as exc:
            raise ValidationFailed(f"invalid balance_sheet dataset: {exc.error_count()} error(s)",
                                   model_id=model_id) from exc
    kind = getattr(dataset, "kind", type(dataset).__name__)
    raise ValidationFailed(f"{model_id} needs a balance_sheet dataset, got {kind!r}", model_id=model_id)


def loans_book(bs: BankBalanceSheet) -> float:
    return sum(a.book_value for a in bs.assets if a.kind == "loans")


def reconciliation_gap(bs: BankBalanceSheet) -> float:
    """|sum EAD - loans book value| / loans book value (0 if both are zero, 1 if only the book is zero)."""
    book = loans_book(bs)
    ead = sum(p.ead for p in bs.loan_pools)
    if book <= 0:
        return 0.0 if ead <= 0 else 1.0
    return abs(ead - book) / book


def check_structure(bs: BankBalanceSheet, model_id: str, *, for_stress: bool) -> None:
    """Raise for data a calculation cannot use. Data-quality issues that still allow a result are findings."""
    n_items = len(bs.assets) + len(bs.loan_pools) + len(bs.deposits) + len(bs.wholesale_funding) + len(bs.hedges)
    if n_items > catalog.LIMITS["max_balance_sheet_items"]:
        raise LimitExceeded(f"{n_items} balance-sheet items exceed {catalog.LIMITS['max_balance_sheet_items']}",
                            model_id=model_id)
    numbers: list[tuple[str, float]] = [("cet1_capital", bs.cet1_capital), ("risk_weighted_assets", bs.risk_weighted_assets),
                                        ("policy_rate", bs.policy_rate)]
    for a in bs.assets:
        numbers += [(f"assets[{a.id}].{k}", v) for k, v in a.model_dump().items() if isinstance(v, float)]
    for p in bs.loan_pools:
        numbers.append((f"loan_pools[{p.segment}].ead", p.ead))
    for d in bs.deposits:
        numbers += [(f"deposits[{d.segment}].balance", d.balance), (f"deposits[{d.segment}].rate", d.rate)]
    for w in bs.wholesale_funding:
        numbers += [(f"wholesale_funding[{w.id}].amount", w.amount), (f"wholesale_funding[{w.id}].rate", w.rate)]
    for h in bs.hedges:
        numbers += [(f"hedges[{h.id}].notional", h.notional), (f"hedges[{h.id}].fixed_rate", h.fixed_rate)]
    bad = [name for name, v in numbers if not math.isfinite(v)]
    if bad:
        raise ValidationFailed(f"non-finite values: {bad[:5]}", model_id=model_id)
    rates = [("policy_rate", bs.policy_rate)] + [(f"assets[{a.id}].coupon_rate", a.coupon_rate) for a in bs.assets] \
        + [(f"hedges[{h.id}].fixed_rate", h.fixed_rate) for h in bs.hedges]
    bad = [name for name, v in rates if v <= -0.5 or v >= 1.0]
    if bad:
        raise ValidationFailed(f"implausible rates (must lie in (-50%, 100%)): {bad[:5]}", model_id=model_id)
    for label, ids in (("asset", [a.id for a in bs.assets]), ("deposit segment", [d.segment for d in bs.deposits]),
                       ("loan pool", [p.segment for p in bs.loan_pools]),
                       ("wholesale line", [w.id for w in bs.wholesale_funding]), ("hedge", [h.id for h in bs.hedges])):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValidationFailed(f"duplicate {label} ids: {dupes}", model_id=model_id)
    for a in bs.assets:
        if a.modified_duration is not None and (not math.isfinite(a.modified_duration) or a.modified_duration < 0):
            raise ValidationFailed(f"assets[{a.id}].modified_duration must be >= 0", model_id=model_id)
        if a.convexity is not None and (not math.isfinite(a.convexity) or a.convexity < 0):
            raise ValidationFailed(f"assets[{a.id}].convexity must be >= 0", model_id=model_id)
    if sum(a.market_value for a in bs.assets) <= 0:
        raise ValidationFailed("total asset market value is zero", model_id=model_id)
    if for_stress:
        gap = reconciliation_gap(bs)
        if gap > MAX_RECONCILIATION_GAP_FOR_STRESS:
            raise ValidationFailed(
                f"loan pools do not reconcile to the loan book (gap {gap:.1%} > "
                f"{MAX_RECONCILIATION_GAP_FOR_STRESS:.0%}); the credit loss would be meaningless",
                model_id=model_id, gap=gap)
