"""Deterministic fakes of every port, so each component can be built and tested in isolation.

They implement behaviour only as far as needed to exercise neighbours; numbers are placeholders,
not risk calculations. Never use them in the composition root.
"""

from __future__ import annotations

import datetime as dt
import itertools
from typing import Any

from . import catalog, rules
from .conformance import resolve_params
from .errors import Conflict, NotFound, ValidationFailed
from .hashing import derive_seed, model_input_hash, run_input_hash, sha256_hex, variation_id
from .tracing import TraceBuilder
from .types import (
    AuditEvent,
    BankBalanceSheet,
    BsAsset,
    CalcRequest,
    ClimateHolding,
    ClimatePortfolio,
    Comparison,
    ControlStrength,
    DataQualityFinding,
    Dataset,
    DepositSegment,
    Evidence,
    FactorEdit,
    FactorSource,
    LoanPool,
    MarketDataset,
    MarketPosition,
    MetricRange,
    ModelOutput,
    ModelSpec,
    Override,
    QualitativeAssessment,
    QualitativeFactor,
    QuestionId,
    QuestionInfo,
    QuestionPlan,
    Report,
    ReviewDecision,
    ReviewSubmission,
    RunRecord,
    RunRequest,
    RunResult,
    RunStatus,
    Severity,
    SignOff,
    Trace,
    VariationResult,
    VariationSpec,
    VerifierFinding,
)

FIXED_NOW = dt.datetime(2026, 11, 24, 12, 0, 0, tzinfo=dt.timezone.utc)
CONTRACT_VERSION_FAKE = "fake"


# ---------------------------------------------------------------------------------------------
# Tiny datasets (valid but not meaningful)
# ---------------------------------------------------------------------------------------------


def fake_dataset(question: QuestionId) -> Dataset:
    if question == QuestionId.Q1:
        dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
        rets = [((i * 7) % 11 - 5) / 1000 for i in range(30)]
        return MarketDataset(
            name="fake book", as_of=dates[-1], synthetic=True, dates=dates,
            positions=[MarketPosition(ticker="AAA", quantity=100, price=50.0),
                       MarketPosition(ticker="BBB", quantity=-40, price=20.0)],
            returns={"AAA": rets, "BBB": [r / 2 for r in rets]},
        )
    if question == QuestionId.Q2:
        return BankBalanceSheet(
            name="fake bank", as_of=dt.date(2026, 11, 1), synthetic=True, policy_rate=0.04,
            assets=[BsAsset(id="cash", kind="cash", book_value=100, market_value=100, coupon_rate=0.0,
                            maturity_years=0, repricing_years=0, hqla_level="1"),
                    BsAsset(id="loans", kind="loans", book_value=800, market_value=790, coupon_rate=0.05,
                            maturity_years=5, repricing_years=1)],
            loan_pools=[LoanPool(segment="retail", ead=800, pd=0.02, lgd=0.4, asset_correlation=0.15)],
            deposits=[DepositSegment(segment="retail", balance=850, insured_share=0.6, rate_beta=0.3,
                                     runoff_slow=0.05, runoff_fast=0.2)],
            cet1_capital=60, risk_weighted_assets=700,
        )
    return ClimatePortfolio(
        name="fake climate book", as_of=dt.date(2026, 11, 1), synthetic=True,
        holdings=[ClimateHolding(issuer="Oilco", sector="energy", market_value=1000, evic=50000, revenue=20000,
                                 scope1=100000, scope2=5000, data_quality=2, emissions_year=2025),
                  ClimateHolding(issuer="Softco", sector="technology", market_value=2000, evic=80000, revenue=10000,
                                 data_quality=None)],
    )


# ---------------------------------------------------------------------------------------------
# Models and registry
# ---------------------------------------------------------------------------------------------


class FakeModel:
    """Returns every non-optional metric of its spec with a deterministic placeholder value."""

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec

    def run(self, dataset: Dataset, params: dict[str, Any], seed: int) -> ModelOutput:
        if dataset.kind != self.spec.dataset_kind.value:
            raise ValidationFailed(f"{self.spec.model_id} needs a {self.spec.dataset_kind.value} dataset")
        eff = resolve_params(self.spec, params)
        h = model_input_hash(self.spec.model_id, dataset, eff, seed)
        tb = TraceBuilder(self.spec.model_id, f"FAKE {self.spec.title}", h, assumptions=["Fake model output."],
                          inputs={"params": eff})
        metrics = {}
        base = int(h[:6], 16) / 0xFFFFFF  # 0..1, deterministic
        for i, m in enumerate(s for s in self.spec.metrics if not s.optional):
            v = round(0.01 + 0.05 * base + 0.001 * i, 6)
            tb.step(m.key, m.description, r"\text{fake}", f"{v}", value=v, unit=m.unit)
            metrics[m.key] = tb.metric(m.key, v, m.unit)
        labels = {k: vals[0] for k, vals in self.spec.labels.items()}
        if self.spec.pass_label:
            labels[self.spec.pass_label] = "fail" if base > 0.5 else "pass"
        return ModelOutput(model_id=self.spec.model_id, params=eff, metrics=metrics, labels=labels,
                           traces=[tb.build({k: m.value for k, m in metrics.items()})])


class FakeRegistry:
    def __init__(self, models: list[Any] | None = None) -> None:
        self._models: dict[str, Any] = {}
        for m in models if models is not None else [FakeModel(s) for s in catalog.MODEL_SPECS.values()]:
            self.register(m)

    def register(self, model: Any) -> None:
        self._models[model.spec.model_id] = model

    def get(self, model_id: str) -> Any:
        if model_id not in self._models:
            raise NotFound(f"unknown model {model_id!r}")
        return self._models[model_id]

    def specs(self, question: QuestionId | None = None) -> list[ModelSpec]:
        return [m.spec for m in self._models.values() if question is None or m.spec.question == question]


# ---------------------------------------------------------------------------------------------
# Services fakes
# ---------------------------------------------------------------------------------------------


class FakePlanner:
    """Plain cartesian product (no applies_when de-duplication) plus extras."""

    def expand(self, plan: QuestionPlan, seed: int) -> list[VariationSpec]:
        dims = plan.grid.dimensions
        out = []
        for combo in itertools.product(*dims.values()) if dims else [()]:
            params = {**plan.grid.fixed, **dict(zip(dims.keys(), combo))}
            vid = variation_id(plan.grid.model_id, params)
            out.append(VariationSpec(variation_id=vid, question=plan.question, model_id=plan.grid.model_id,
                                     params=params, seed=derive_seed(seed, vid)))
        for extra in plan.extras:
            vid = variation_id(extra.model_id, extra.params)
            out.append(VariationSpec(variation_id=vid, question=plan.question, model_id=extra.model_id,
                                     params=extra.params, seed=derive_seed(seed, vid), role="extra"))
        return out[: plan.max_variations]


class FakeExecutor:
    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def execute(self, spec: VariationSpec, dataset: Dataset) -> VariationResult:
        try:
            out = self.registry.get(spec.model_id).run(dataset, spec.params, spec.seed)
            return VariationResult(spec=spec, output=out, duration_ms=1.0)
        except Exception as exc:  # captured, never raised
            return VariationResult(spec=spec, error=f"{type(exc).__name__}: {exc}", duration_ms=1.0)


class FakeComparator:
    def compare(self, plan: QuestionPlan, results: list[VariationResult]) -> Comparison:
        ranges: dict[str, MetricRange] = {}
        grid = [r.output for r in results if r.output and r.spec.role == "grid"]
        for key in grid[0].metrics if grid else []:
            vals = sorted(o.metrics[key].value for o in grid if key in o.metrics)
            ranges[key] = MetricRange(unit=grid[0].metrics[key].unit, min=vals[0], median=vals[len(vals) // 2],
                                      max=vals[-1], n=len(vals))
        return Comparison(question=plan.question, metric_ranges=ranges)


class FakeVerifier:
    def check_outputs(self, results: list[VariationResult]) -> list[VerifierFinding]:
        return []

    def verify_text(self, location: str, text: str, results: list[VariationResult]) -> list[VerifierFinding]:
        return []


class FakeAssessor:
    def assess(self, question, dataset, results, comparison) -> QualitativeAssessment:
        inh, res = rules.rate(3, 3, ControlStrength.ADEQUATE)
        f = QualitativeFactor(factor_id="fake_factor", name="Fake factor", description="Placeholder.",
                              likelihood=3, impact=3, control=ControlStrength.ADEQUATE, inherent=inh, residual=res,
                              evidence=[Evidence(kind="note", ref="fake", description="fake")],
                              rationale="Placeholder rationale.", source=FactorSource.RULE)
        return QualitativeAssessment(question=question, factors=[f], overall=rules.overall_rating([res]),
                                     method_note="Fake assessor.")

    def apply_edits(self, assessment, edits: list[FactorEdit], reviewer: str, at: dt.datetime) -> QualitativeAssessment:
        factors = {f.factor_id: f for f in assessment.factors}
        overrides = list(assessment.overrides)
        for e in edits:
            if e.factor_id not in factors:
                raise ValidationFailed(f"unknown factor {e.factor_id!r}")
            f = factors[e.factor_id]
            upd = {k: v for k, v in e.model_dump().items() if k in ("likelihood", "impact", "control", "rationale")
                   and v is not None}
            for k, v in upd.items():
                overrides.append(Override(factor_id=f.factor_id, field=k, old=getattr(f, k), new=v, reason=e.reason,
                                          by=reviewer, at=at))
            f = f.model_copy(update={**upd, "source": FactorSource.ANALYST})
            inh, res = rules.rate(f.likelihood, f.impact, f.control)
            factors[e.factor_id] = f.model_copy(update={"inherent": inh, "residual": res})
        fl = list(factors.values())
        return assessment.model_copy(update={"factors": fl, "overrides": overrides,
                                             "overall": rules.overall_rating([f.residual for f in fl])})


class FakeStore:
    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.requests: dict[str, RunRequest] = {}
        self.results: dict[str, RunResult] = {}
        self.traces: dict[str, Trace] = {}
        self.signoffs: dict[str, SignOff] = {}
        self.audit: list[AuditEvent] = []

    def create_run(self, record, request):
        self.runs[record.run_id], self.requests[record.run_id] = record, request

    def update_run(self, record):
        self.get_run(record.run_id)
        self.runs[record.run_id] = record

    def get_run(self, run_id):
        if run_id not in self.runs:
            raise NotFound(f"unknown run {run_id!r}")
        return self.runs[run_id]

    def get_request(self, run_id):
        self.get_run(run_id)
        return self.requests[run_id]

    def list_runs(self, limit=100):
        return sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)[:limit]

    def save_result(self, result):
        self.results[result.run.run_id] = result
        for v in result.variations:
            for t in v.output.traces if v.output else []:
                self.traces[t.trace_id] = t

    def get_result(self, run_id):
        if run_id not in self.results:
            raise NotFound(f"no result for run {run_id!r}")
        return self.results[run_id]

    def get_trace(self, trace_id):
        if trace_id not in self.traces:
            raise NotFound(f"unknown trace {trace_id!r}")
        return self.traces[trace_id]

    def save_signoff(self, run_id, signoff):
        self.signoffs[run_id] = signoff

    def get_signoff(self, run_id):
        return self.signoffs.get(run_id)

    def append_audit(self, event):
        self.audit.append(event)

    def audit_log(self, run_id):
        return [e for e in self.audit if e.run_id == run_id]


class FakeReporter:
    def build(self, result: RunResult, signoff: SignOff | None) -> Report:
        lines = [f"# Run {result.run.run_id}", "", "FAKE REPORT"]
        return Report(run=result.run, headline=["Fake headline."], comparison=result.comparison,
                      assessment=result.assessment, signoff=signoff, markdown="\n".join(lines))


# ---------------------------------------------------------------------------------------------
# RunService fake (synchronous, in memory): for adapters, the web UI fixtures and contract tests
# ---------------------------------------------------------------------------------------------


class FakeRunService:
    def __init__(self) -> None:
        self.registry = FakeRegistry()
        self.planner, self.executor = FakePlanner(), FakeExecutor(self.registry)
        self.comparator, self.assessor = FakeComparator(), FakeAssessor()
        self.store, self.reporter = FakeStore(), FakeReporter()
        self._n = 0

    def questions(self) -> list[QuestionInfo]:
        return list(catalog.QUESTIONS.values())

    def list_models(self, question: QuestionId | None = None) -> list[ModelSpec]:
        return self.registry.specs(question)

    def sample_dataset(self, question: QuestionId) -> Dataset:
        return fake_dataset(question)

    def validate(self, dataset: Dataset) -> list[DataQualityFinding]:
        return [DataQualityFinding(check="fake_check", severity=Severity.INFO, field="dataset", message="Fake.")]

    def calc(self, request: CalcRequest) -> ModelOutput:
        return self.registry.get(request.model_id).run(request.dataset, request.params, request.seed)

    def start_run(self, request: RunRequest, *, wait: bool = False) -> RunRecord:
        plan = request.plan or catalog.DEFAULT_PLANS[request.question]
        if plan.question != request.question:
            raise ValidationFailed("plan.question does not match request.question")
        self._n += 1
        run_id = f"run-{self._n:04d}"
        specs = self.planner.expand(plan, request.seed)
        rec = RunRecord(run_id=run_id, question=request.question, status=RunStatus.RUNNING, created_at=FIXED_NOW,
                        updated_at=FIXED_NOW, input_hash=run_input_hash(request.question.value, request.dataset, plan,
                                                                        request.seed),
                        contract_version=CONTRACT_VERSION_FAKE, n_variations=len(specs),
                        dataset_name=request.dataset.name, synthetic=request.dataset.synthetic)
        self.store.create_run(rec, request)
        results = [self.executor.execute(s, request.dataset) for s in specs]
        comparison = self.comparator.compare(plan, results)
        assessment = self.assessor.assess(request.question, request.dataset, results, comparison)
        rec = rec.model_copy(update={"status": RunStatus.AWAITING_REVIEW})
        self.store.update_run(rec)
        self.store.save_result(RunResult(run=rec, plan=plan, variations=results, comparison=comparison,
                                         assessment=assessment))
        return rec

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        return self.store.list_runs(limit)

    def get_run(self, run_id: str) -> RunRecord:
        return self.store.get_run(run_id)

    def get_result(self, run_id: str) -> RunResult:
        rec = self.store.get_run(run_id)
        if rec.status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED):
            raise Conflict(f"run {run_id} is {rec.status.value}")
        return self.store.get_result(run_id).model_copy(update={"run": rec})

    def get_trace(self, trace_id: str) -> Trace:
        return self.store.get_trace(trace_id)

    def submit_review(self, run_id: str, review: ReviewSubmission) -> RunRecord:
        rec = self.store.get_run(run_id)
        if rec.status != RunStatus.AWAITING_REVIEW:
            raise Conflict(f"run {run_id} is {rec.status.value}, not awaiting_review")
        result = self.store.get_result(run_id)
        assessment = self.assessor.apply_edits(result.assessment, review.factor_edits, review.reviewer, FIXED_NOW)
        status = RunStatus.APPROVED if review.decision == ReviewDecision.APPROVE else RunStatus.REJECTED
        rec = rec.model_copy(update={"status": status})
        self.store.update_run(rec)
        self.store.save_result(result.model_copy(update={"run": rec, "assessment": assessment}))
        self.store.save_signoff(run_id, SignOff(reviewer=review.reviewer, decision=review.decision,
                                                comment=review.comment, at=FIXED_NOW))
        return rec

    def get_report(self, run_id: str) -> Report:
        return self.reporter.build(self.get_result(run_id), self.store.get_signoff(run_id))

    def audit_log(self, run_id: str) -> list[AuditEvent]:
        self.store.get_run(run_id)
        return self.store.audit_log(run_id)


def fake_digest(obj: Any) -> str:
    return sha256_hex(obj)[:12]
