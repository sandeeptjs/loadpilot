from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import UUID

from .models import AuditEvent, RunState, TestRun, utcnow

TERMINAL = {RunState.COMPLETED, RunState.FAILED, RunState.CANCELED, RunState.TIMED_OUT}
TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.DISCOVERING_APPLICATION, RunState.CANCELED, RunState.FAILED},
    RunState.DISCOVERING_APPLICATION: {RunState.GENERATING_DATA, RunState.FAILED, RunState.CANCELED},
    RunState.GENERATING_DATA: {RunState.PLANNING, RunState.FAILED, RunState.CANCELED},
    RunState.PLANNING: {RunState.GENERATING_SCRIPT, RunState.FAILED, RunState.CANCELED},
    RunState.GENERATING_SCRIPT: {RunState.VALIDATING, RunState.FAILED, RunState.CANCELED},
    RunState.VALIDATING: {RunState.SCHEDULED, RunState.QUEUED, RunState.FAILED, RunState.CANCELED},
    RunState.SCHEDULED: {RunState.QUEUED, RunState.CANCELED, RunState.FAILED},
    RunState.QUEUED: {RunState.INITIALIZING, RunState.CANCELED, RunState.FAILED},
    RunState.INITIALIZING: {RunState.RUNNING, RunState.CANCELED, RunState.FAILED},
    RunState.RUNNING: {RunState.COLLECTING_TELEMETRY, RunState.CANCELED, RunState.FAILED, RunState.TIMED_OUT},
    RunState.COLLECTING_TELEMETRY: {RunState.ANALYZING, RunState.FAILED, RunState.CANCELED},
    RunState.ANALYZING: {RunState.COMPLETED, RunState.FAILED, RunState.CANCELED},
}


class InvalidTransition(ValueError):
    pass


class RunStore:
    def __init__(self, path: str | Path = "loadpilot.db") -> None:
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS entities (kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind,id))")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (run_id TEXT PRIMARY KEY, due REAL NOT NULL, status TEXT NOT NULL, owner TEXT, heartbeat REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, timestamp TEXT NOT NULL, body TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sample_run ON samples(run_id,id)")
            db.execute('CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, owner TEXT, expires REAL)')
            db.commit()

    def create(self, run: TestRun) -> TestRun:
        with self.lock, self._connect() as db:
            db.execute("INSERT INTO runs(id,state,body,updated_at) VALUES(?,?,?,?)", (str(run.id), run.state.value, run.model_dump_json(), utcnow().isoformat()))
            db.commit()
        return run

    def get(self, run_id: UUID | str) -> TestRun:
        with self._connect() as db:
            row = db.execute("SELECT body FROM runs WHERE id=?", (str(run_id),)).fetchone()
        if not row:
            raise KeyError(str(run_id))
        return TestRun.model_validate_json(row["body"])

    def list(self, limit: int = 100) -> list[TestRun]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM runs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [TestRun.model_validate_json(row["body"]) for row in rows]

    def save(self, run: TestRun) -> TestRun:
        with self.lock, self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM runs WHERE id=?', (str(run.id),)).fetchone()
            if row and RunState(row['state']) in TERMINAL and row['state'] != run.state.value:
                raise InvalidTransition('A terminal run cannot be overwritten by stale state')
            db.execute("UPDATE runs SET state=?, body=?, updated_at=? WHERE id=?", (run.state.value, run.model_dump_json(), utcnow().isoformat(), str(run.id)))
            db.commit()
        return run

    def update(self, run_id, **fields) -> TestRun:
        with self.lock:
            return self.save(self.get(run_id).model_copy(update=fields))

    def enqueue(self, run_id, due: float) -> None:
        with self.lock, self._connect() as db:
            db.execute("INSERT INTO jobs(run_id,due,status) VALUES(?,?,'pending') ON CONFLICT(run_id) DO UPDATE SET due=excluded.due WHERE jobs.status='pending'", (str(run_id), due))

    def claim(self, owner: str, now: float):
        with self.lock, self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM maintenance WHERE expires>?', (now,)).fetchone():
                return None
            # One active workload per database prevents overlapping sandbox measurements.
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                return None
            row = db.execute("SELECT run_id FROM jobs WHERE status='pending' AND due<=? ORDER BY due LIMIT 1", (now,)).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',owner=?,heartbeat=? WHERE run_id=?", (owner, now, row['run_id']))
                return row['run_id']
        return None

    def reserve_maintenance(self, owner, now):
        with self.lock, self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone() or db.execute('SELECT 1 FROM maintenance WHERE expires>?', (now,)).fetchone():
                raise ValueError('Wait for the active workload or maintenance action to finish')
            db.execute('INSERT OR REPLACE INTO maintenance VALUES(1,?,?)', (owner, now + 30))

    def release_maintenance(self, owner):
        with self._connect() as db:
            db.execute('DELETE FROM maintenance WHERE owner=?', (owner,))

    def finish_job(self, run_id, status='done'):
        with self._connect() as db:
            db.execute('UPDATE jobs SET status=? WHERE run_id=?', (status, str(run_id)))

    def heartbeat(self, run_id, owner, now):
        with self._connect() as db:
            db.execute("UPDATE jobs SET heartbeat=? WHERE run_id=? AND owner=? AND status='running'", (now, str(run_id), owner))

    def stale_jobs(self, cutoff):
        with self._connect() as db:
            return [row['run_id'] for row in db.execute("SELECT run_id FROM jobs WHERE status='running' AND heartbeat<?", (cutoff,))]

    def add_sample(self, run_id, timestamp, values):
        with self._connect() as db:
            db.execute('INSERT INTO samples(run_id,timestamp,body) VALUES(?,?,?)', (str(run_id), timestamp, json.dumps(values, allow_nan=False)))

    def samples(self, run_id, after=0, limit=1000):
        with self._connect() as db:
            rows = db.execute('SELECT id,timestamp,body FROM samples WHERE run_id=? AND id>? ORDER BY id LIMIT ?', (str(run_id), after, limit)).fetchall()
        return [{'id': row['id'], 'timestamp': row['timestamp'], 'metrics': json.loads(row['body'])} for row in rows]

    def transition(self, run_id: UUID | str, target: RunState, *, error: str | None = None, cancellation_reason: str | None = None) -> TestRun:
        with self.lock:
            run = self.get(run_id)
            if target not in TRANSITIONS.get(run.state, set()):
                raise InvalidTransition(f"{run.state.value} -> {target.value} is not allowed")
            update = {"state": target}
            now = utcnow()
            if target == RunState.RUNNING:
                update["started_at"] = now
            if target in TERMINAL:
                update["finished_at"] = now
            if error:
                update["error"] = error
            if cancellation_reason:
                update["cancellation_reason"] = cancellation_reason
            return self.save(run.model_copy(update=update))

    def append_audit(self, event: AuditEvent) -> None:
        with self.lock, self._connect() as db:
            db.execute("INSERT INTO audit_events(id,timestamp,action,body) VALUES(?,?,?,?)", (str(event.id), event.timestamp.isoformat(), event.action, event.model_dump_json()))
            db.commit()

    def audit(self, limit: int = 200) -> list[AuditEvent]:
        with self._connect() as db:
            rows = db.execute("SELECT body FROM audit_events ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [AuditEvent.model_validate_json(row["body"]) for row in rows]

    def put_entity(self, kind: str, entity) -> None:
        body = entity.model_dump_json() if hasattr(entity, "model_dump_json") else json.dumps(entity)
        entity_id = str(entity.id)
        with self.lock, self._connect() as db:
            db.execute("INSERT INTO entities(kind,id,body,updated_at) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at", (kind, entity_id, body, utcnow().isoformat()))
            db.commit()

    def get_entity(self, kind: str, entity_id: UUID | str, model):
        with self._connect() as db:
            row = db.execute("SELECT body FROM entities WHERE kind=? AND id=?", (kind, str(entity_id))).fetchone()
        if not row:
            raise KeyError(f"{kind}:{entity_id}")
        return model.model_validate_json(row["body"])

    def list_entities(self, kind: str, model, limit: int = 100):
        with self._connect() as db:
            rows = db.execute("SELECT body FROM entities WHERE kind=? ORDER BY updated_at DESC LIMIT ?", (kind, limit)).fetchall()
        return [model.model_validate_json(row["body"]) for row in rows]
