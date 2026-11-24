"""Export JSON Schemas and example payloads for non-Python clients (web UI, WPF, other apps).

    python -m riskbot.contract.export

Writes riskbot/contract/generated/schema/*.json and riskbot/contract/generated/fixtures/*.json.
Fixtures come from the fakes: their numbers are placeholders, their shapes are exact.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from . import CONTRACT_VERSION, catalog
from .fakes import FakeRunService
from .types import (
    CalcRequest,
    Dataset,
    ErrorBody,
    FactorEdit,
    ModelOutput,
    ModelSpec,
    QuestionId,
    QuestionInfo,
    Report,
    ReviewDecision,
    ReviewSubmission,
    RunRecord,
    RunRequest,
    RunResult,
    Trace,
)

OUT = Path(__file__).resolve().parent / "generated"

SCHEMAS = {
    "Dataset": TypeAdapter(Dataset),
    "ModelSpec": TypeAdapter(ModelSpec),
    "ModelOutput": TypeAdapter(ModelOutput),
    "CalcRequest": TypeAdapter(CalcRequest),
    "QuestionInfo": TypeAdapter(QuestionInfo),
    "RunRequest": TypeAdapter(RunRequest),
    "RunRecord": TypeAdapter(RunRecord),
    "RunResult": TypeAdapter(RunResult),
    "Trace": TypeAdapter(Trace),
    "ReviewSubmission": TypeAdapter(ReviewSubmission),
    "Report": TypeAdapter(Report),
    "ErrorBody": TypeAdapter(ErrorBody),
}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    for name, ta in SCHEMAS.items():
        _dump(OUT / "schema" / f"{name}.json", ta.json_schema(mode="serialization"))

    svc = FakeRunService()
    fx = OUT / "fixtures"
    _dump(fx / "contract_version.json", {"contract_version": CONTRACT_VERSION})
    _dump(fx / "questions.json", [q.model_dump(mode="json") for q in svc.questions()])
    _dump(fx / "models.json", [m.model_dump(mode="json") for m in catalog.MODEL_SPECS.values()])
    for q in QuestionId:
        ds = svc.sample_dataset(q)
        _dump(fx / f"sample_{q.value}.json", ds.model_dump(mode="json"))
        rec = svc.start_run(RunRequest(question=q, dataset=ds), wait=True)
        res = svc.get_result(rec.run_id)
        _dump(fx / f"run_record_{q.value}.json", rec.model_dump(mode="json"))
        _dump(fx / f"run_result_{q.value}.json", res.model_dump(mode="json"))
        trace = next(t for v in res.variations if v.output for t in v.output.traces)
        _dump(fx / f"trace_{q.value}.json", trace.model_dump(mode="json"))
        fid = res.assessment.factors[0].factor_id
        svc.submit_review(rec.run_id, ReviewSubmission(decision=ReviewDecision.APPROVE, reviewer="analyst",
                                                       factor_edits=[FactorEdit(factor_id=fid, impact=4,
                                                                                reason="example")]))
        _dump(fx / f"report_{q.value}.json", svc.get_report(rec.run_id).model_dump(mode="json"))
    _dump(fx / "error_not_found.json", ErrorBody(code="not_found", message="unknown run 'x'").model_dump(mode="json"))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
