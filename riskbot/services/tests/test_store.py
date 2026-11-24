"""SQLite store tests: round-trips, errors, ordering, trace indexing, concurrency."""

import datetime as dt
import threading

import pytest

import riskbot.services as services
from riskbot.contract import catalog
from riskbot.contract.errors import Conflict, NotFound
from riskbot.contract.fakes import FIXED_NOW, FakeAssessor, fake_dataset
from riskbot.contract.types import (
    AuditEvent,
    ReviewDecision,
    RunRecord,
    RunRequest,
    RunResult,
    RunStatus,
    QuestionId,
    SignOff,
)

Q2 = QuestionId.Q2


def _record(run_id="run-0001", minutes=0, status=RunStatus.PENDING):
    t = FIXED_NOW + dt.timedelta(minutes=minutes)
    return RunRecord(run_id=run_id, question=Q2, status=status, created_at=t, updated_at=t, input_hash="h" * 64,
                     contract_version="2.0.0", n_variations=35, dataset_name="fake bank", synthetic=True)


def _request():
    return RunRequest(question=Q2, dataset=fake_dataset(Q2))


def _result(fake_registry, record):
    plan = catalog.DEFAULT_PLANS[Q2]
    specs = services.planner().expand(plan, 1)
    res = services.executor(fake_registry).execute_many(specs, fake_dataset(Q2))
    comp = services.comparator().compare(plan, res)
    a = FakeAssessor().assess(Q2, fake_dataset(Q2), res, comp)
    return RunResult(run=record, plan=plan, variations=res, comparison=comp, assessment=a)


@pytest.fixture
def store():
    return services.sqlite_store(":memory:")


def test_run_round_trip(store):
    rec, req = _record(), _request()
    store.create_run(rec, req)
    assert store.get_run("run-0001") == rec
    assert store.get_request("run-0001") == req
    upd = rec.model_copy(update={"status": RunStatus.RUNNING, "updated_at": FIXED_NOW + dt.timedelta(seconds=5)})
    store.update_run(upd)
    assert store.get_run("run-0001") == upd


def test_errors(store):
    with pytest.raises(NotFound):
        store.get_run("x")
    with pytest.raises(NotFound):
        store.get_request("x")
    with pytest.raises(NotFound):
        store.update_run(_record("x"))
    with pytest.raises(NotFound):
        store.get_result("x")
    with pytest.raises(NotFound):
        store.get_trace("q1.var-000000000000")
    store.create_run(_record(), _request())
    with pytest.raises(Conflict):
        store.create_run(_record(), _request())
    with pytest.raises(NotFound):
        store.get_result("run-0001")
    assert store.get_signoff("run-0001") is None


def test_list_runs_newest_first(store):
    for i, m in enumerate([5, 1, 9, 3]):
        store.create_run(_record(f"run-{i}", minutes=m), _request())
    assert [r.run_id for r in store.list_runs()] == ["run-2", "run-0", "run-3", "run-1"]
    assert [r.run_id for r in store.list_runs(limit=2)] == ["run-2", "run-0"]


def test_list_runs_normalises_timezones(store):
    cet = dt.timezone(dt.timedelta(hours=1))
    a = _record("a").model_copy(update={"created_at": dt.datetime(2026, 11, 24, 12, 30, tzinfo=cet)})  # 11:30Z
    b = _record("b").model_copy(update={"created_at": dt.datetime(2026, 11, 24, 12, 0, tzinfo=dt.timezone.utc)})
    store.create_run(a, _request())
    store.create_run(b, _request())
    assert [r.run_id for r in store.list_runs()] == ["b", "a"]


def test_result_and_traces(store, fake_registry):
    rec = _record()
    store.create_run(rec, _request())
    result = _result(fake_registry, rec)
    store.save_result(result)
    assert store.get_result("run-0001") == result
    traces = [t for v in result.variations if v.output for t in v.output.traces]
    assert traces
    for t in traces:
        assert store.get_trace(t.trace_id) == t
    # re-saving replaces the result and the trace index
    smaller = result.model_copy(update={"variations": result.variations[:1]})
    store.save_result(smaller)
    assert store.get_result("run-0001") == smaller
    assert store.get_trace(traces[0].trace_id) == traces[0]
    with pytest.raises(NotFound):
        store.get_trace(traces[-1].trace_id)


def test_save_result_requires_run(store, fake_registry):
    with pytest.raises(NotFound):
        store.save_result(_result(fake_registry, _record("ghost")))


def test_signoff_and_audit(store):
    store.create_run(_record(), _request())
    so = SignOff(reviewer="ana", decision=ReviewDecision.APPROVE, comment="ok", at=FIXED_NOW)
    store.save_signoff("run-0001", so)
    assert store.get_signoff("run-0001") == so
    so2 = so.model_copy(update={"comment": "revised"})
    store.save_signoff("run-0001", so2)
    assert store.get_signoff("run-0001") == so2
    events = [AuditEvent(run_id="run-0001", at=FIXED_NOW, actor="system", event=f"e{i}", detail={"i": i})
              for i in range(5)]
    for e in events:
        store.append_audit(e)
    store.append_audit(AuditEvent(run_id="other", at=FIXED_NOW, actor="system", event="x"))
    assert store.audit_log("run-0001") == events
    assert store.audit_log("nobody") == []


def test_file_persistence(tmp_path):
    path = str(tmp_path / "runs.sqlite")
    s1 = services.sqlite_store(path)
    s1.create_run(_record(), _request())
    s1.close()
    s2 = services.sqlite_store(path)
    assert s2.get_run("run-0001") == _record()


def test_concurrency_smoke(store):
    errors = []

    def worker(n):
        try:
            for i in range(20):
                rid = f"run-{n}-{i}"
                store.create_run(_record(rid, minutes=i), _request())
                store.append_audit(AuditEvent(run_id=rid, at=FIXED_NOW, actor="system", event="created"))
                store.update_run(_record(rid, minutes=i, status=RunStatus.RUNNING))
                assert store.get_run(rid).status == RunStatus.RUNNING
                store.list_runs(5)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.list_runs(1000)) == 160
    assert all(len(store.audit_log(f"run-{n}-{i}")) == 1 for n in range(8) for i in range(20))
