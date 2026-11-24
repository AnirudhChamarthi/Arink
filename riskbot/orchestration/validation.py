"""Synchronous input checks shared by ``start_run``, ``calc`` and ``validate``.

Everything here runs *before* a run exists, so a bad request never leaves a half-created run behind.
All failures are contract errors (``ValidationFailed`` / ``LimitExceeded``) that adapters map to
HTTP / MCP errors.
"""

from __future__ import annotations

from riskbot.contract import catalog
from riskbot.contract.errors import LimitExceeded, ValidationFailed
from riskbot.contract.types import (
    BankBalanceSheet,
    ClimatePortfolio,
    DatasetKind,
    MarketDataset,
    QuestionId,
    QuestionPlan,
    RunRequest,
)


def dataset_kind(dataset: object) -> DatasetKind:
    """Return the ``DatasetKind`` of a dataset (its ``kind`` discriminator)."""
    try:
        return DatasetKind(getattr(dataset, "kind"))
    except (AttributeError, ValueError) as exc:
        raise ValidationFailed(f"not a contract Dataset: {type(dataset).__name__}") from exc


def question_for_kind(kind: DatasetKind) -> QuestionId:
    """The question whose catalogue entry uses datasets of ``kind`` (one question per kind)."""
    for q, info in catalog.QUESTIONS.items():
        if info.dataset_kind == kind:
            return q
    raise ValidationFailed(f"no question uses {kind.value} datasets")  # pragma: no cover - catalogue invariant


def check_dataset_kind(dataset: object, expected: DatasetKind, what: str) -> None:
    """Raise ``ValidationFailed`` unless ``dataset`` is of the ``expected`` kind."""
    got = dataset_kind(dataset)
    if got != expected:
        raise ValidationFailed(
            f"{what} needs a {expected.value} dataset, got {got.value}",
            expected=expected.value,
            got=got.value,
        )


def check_limits(dataset: object) -> None:
    """Enforce ``catalog.LIMITS`` on dataset size; raises ``LimitExceeded`` naming the limit."""
    lim = catalog.LIMITS

    def over(name: str, n: int, limit_key: str) -> None:
        if n > lim[limit_key]:
            raise LimitExceeded(f"{name}: {n} exceeds the limit of {lim[limit_key]}", limit=limit_key, value=n)

    if isinstance(dataset, MarketDataset):
        over("positions", len(dataset.positions), "max_positions")
        over("history days", len(dataset.dates), "max_history_days")
    elif isinstance(dataset, BankBalanceSheet):
        items = (len(dataset.assets) + len(dataset.loan_pools) + len(dataset.deposits)
                 + len(dataset.wholesale_funding) + len(dataset.hedges))
        over("balance-sheet items", items, "max_balance_sheet_items")
    elif isinstance(dataset, ClimatePortfolio):
        over("holdings", len(dataset.holdings), "max_holdings")
    else:
        raise ValidationFailed(f"not a contract Dataset: {type(dataset).__name__}")


def resolve_plan(request: RunRequest) -> QuestionPlan:
    """``request.plan`` or the question's default; checks dataset kind, limits and plan/question match."""
    info = catalog.QUESTIONS[request.question]
    check_dataset_kind(request.dataset, info.dataset_kind, f"question {request.question.value}")
    check_limits(request.dataset)
    plan = request.plan or catalog.DEFAULT_PLANS[request.question]
    if plan.question != request.question:
        raise ValidationFailed(
            f"plan.question {plan.question.value} does not match request.question {request.question.value}"
        )
    return plan
