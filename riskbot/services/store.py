"""SQLite run store (``ports.RunStore``).

Schema (created on construction, ``CREATE TABLE IF NOT EXISTS``)::

    runs     (run_id PK, created_at TEXT, record JSON, request JSON)
    results  (run_id PK, json)
    traces   (trace_id PK, run_id, json)            -- index of every trace of a saved result
    signoffs (run_id PK, json)
    audit    (id INTEGER PK AUTOINCREMENT, run_id, json)   -- id gives insertion order

JSON columns are written with ``model_dump_json`` and read with ``model_validate_json``, so every value
round-trips through the contract types exactly (unknown fields would fail loudly on read).

Guarantees
----------
* Thread-safe: one connection (``check_same_thread=False``) guarded by a re-entrant lock; every write is
  one transaction. ``":memory:"`` therefore shares a single in-memory database across threads.
* ``create_run`` on an existing id raises ``Conflict``; ``update_run``/``get_run``/``get_request``/
  ``get_result``/``get_trace`` raise ``NotFound``; ``save_result``/``save_signoff`` for an unknown run
  raise ``NotFound``. ``append_audit`` accepts any run id (the audit log is append-only and may record
  events, such as a rejected request, before or without a run row).
* ``list_runs`` is newest first (``created_at`` normalised to UTC, ties broken by insertion order).
* ``save_result`` upserts and re-indexes the run's traces: re-saving replaces the previous index. A trace
  id produced by two runs (identical inputs give identical ids) points to the run that saved it last;
  the content is identical by construction.
* ``audit_log`` is oldest first.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from riskbot.contract.errors import Conflict, NotFound
from riskbot.contract.types import AuditEvent, RunRecord, RunRequest, RunResult, SignOff, Trace

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    record     TEXT NOT NULL,
    request    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_created ON runs (created_at);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT PRIMARY KEY REFERENCES runs (run_id),
    json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    run_id   TEXT NOT NULL REFERENCES runs (run_id),
    json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS traces_run ON traces (run_id);
CREATE TABLE IF NOT EXISTS signoffs (
    run_id TEXT PRIMARY KEY REFERENCES runs (run_id),
    json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_run ON audit (run_id, id);
"""


def _utc_key(t: dt.datetime) -> str:
    """Sortable UTC timestamp text; naive datetimes are taken to be UTC."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


class SqliteRunStore:
    """``RunStore`` on SQLite; see the module docstring."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(_SCHEMA)

    # -- plumbing -------------------------------------------------------------------------------
    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _one(self, sql: str, args: tuple) -> tuple | None:
        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def _require_run(self, conn: sqlite3.Connection, run_id: str) -> None:
        if conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is None:
            raise NotFound(f"unknown run {run_id!r}", run_id=run_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- runs -----------------------------------------------------------------------------------
    def create_run(self, record: RunRecord, request: RunRequest) -> None:
        with self._tx() as c:
            try:
                c.execute("INSERT INTO runs (run_id, created_at, record, request) VALUES (?, ?, ?, ?)",
                          (record.run_id, _utc_key(record.created_at), record.model_dump_json(),
                           request.model_dump_json()))
            except sqlite3.IntegrityError:
                raise Conflict(f"run {record.run_id!r} already exists", run_id=record.run_id) from None

    def update_run(self, record: RunRecord) -> None:
        with self._tx() as c:
            cur = c.execute("UPDATE runs SET record = ?, created_at = ? WHERE run_id = ?",
                            (record.model_dump_json(), _utc_key(record.created_at), record.run_id))
            if cur.rowcount == 0:
                raise NotFound(f"unknown run {record.run_id!r}", run_id=record.run_id)

    def get_run(self, run_id: str) -> RunRecord:
        row = self._one("SELECT record FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise NotFound(f"unknown run {run_id!r}", run_id=run_id)
        return RunRecord.model_validate_json(row[0])

    def get_request(self, run_id: str) -> RunRequest:
        row = self._one("SELECT request FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise NotFound(f"unknown run {run_id!r}", run_id=run_id)
        return RunRequest.model_validate_json(row[0])

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT record FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (max(0, int(limit)),)
            ).fetchall()
        return [RunRecord.model_validate_json(r[0]) for r in rows]

    # -- results and traces ---------------------------------------------------------------------
    def save_result(self, result: RunResult) -> None:
        run_id = result.run.run_id
        traces = {t.trace_id: t for v in result.variations if v.output for t in v.output.traces}
        with self._tx() as c:
            self._require_run(c, run_id)
            c.execute("INSERT INTO results (run_id, json) VALUES (?, ?) "
                      "ON CONFLICT (run_id) DO UPDATE SET json = excluded.json", (run_id, result.model_dump_json()))
            c.execute("DELETE FROM traces WHERE run_id = ?", (run_id,))
            c.executemany("INSERT INTO traces (trace_id, run_id, json) VALUES (?, ?, ?) "
                          "ON CONFLICT (trace_id) DO UPDATE SET run_id = excluded.run_id, json = excluded.json",
                          [(tid, run_id, t.model_dump_json()) for tid, t in traces.items()])

    def get_result(self, run_id: str) -> RunResult:
        row = self._one("SELECT json FROM results WHERE run_id = ?", (run_id,))
        if row is None:
            raise NotFound(f"no result for run {run_id!r}", run_id=run_id)
        return RunResult.model_validate_json(row[0])

    def get_trace(self, trace_id: str) -> Trace:
        row = self._one("SELECT json FROM traces WHERE trace_id = ?", (trace_id,))
        if row is None:
            raise NotFound(f"unknown trace {trace_id!r}", trace_id=trace_id)
        return Trace.model_validate_json(row[0])

    # -- sign-off and audit ---------------------------------------------------------------------
    def save_signoff(self, run_id: str, signoff: SignOff) -> None:
        with self._tx() as c:
            self._require_run(c, run_id)
            c.execute("INSERT INTO signoffs (run_id, json) VALUES (?, ?) "
                      "ON CONFLICT (run_id) DO UPDATE SET json = excluded.json", (run_id, signoff.model_dump_json()))

    def get_signoff(self, run_id: str) -> SignOff | None:
        row = self._one("SELECT json FROM signoffs WHERE run_id = ?", (run_id,))
        return SignOff.model_validate_json(row[0]) if row else None

    def append_audit(self, event: AuditEvent) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO audit (run_id, json) VALUES (?, ?)", (event.run_id, event.model_dump_json()))

    def audit_log(self, run_id: str) -> list[AuditEvent]:
        with self._lock:
            rows = self._conn.execute("SELECT json FROM audit WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [AuditEvent.model_validate_json(r[0]) for r in rows]
