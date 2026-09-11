#!/usr/bin/env python3
"""Small durable SQLite store for worker, task, dependency, and audit state."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

STATES = {"starting", "ready", "working", "waiting", "blocked", "reviewing", "done", "failed", "disconnected", "recovering"}
TERMINAL_STATES = {"done", "failed"}
ALLOWED = {
    "starting": {"ready", "failed", "disconnected"},
    "ready": {"working", "waiting", "failed", "disconnected"},
    "working": {"ready", "waiting", "blocked", "reviewing", "done", "failed", "disconnected"},
    "waiting": {"ready", "working", "blocked", "done", "failed", "disconnected"},
    "blocked": {"working", "failed", "disconnected"},
    "reviewing": {"working", "done", "failed", "blocked"},
    "done": set(), "failed": {"recovering"}, "disconnected": {"recovering", "failed"},
    "recovering": {"ready", "working", "failed", "disconnected"},
}


def db_path() -> Path:
    raw = os.environ.get("AGENT_ORCHESTRATION_DB")
    return Path(raw) if raw else Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")) / "agent-orchestration.db"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript("""
        create table if not exists workers (
          id text primary key, name text not null unique, role text, agent_type text not null, parent_id text,
          state text not null, ref_json text, topology_json text, task_id text,
          last_activity real not null, health_json text not null default '{}', retries integer not null default 0,
          created_at real not null, updated_at real not null);
        create table if not exists tasks (
          id text primary key, title text not null, parent_id text, owner_id text, state text not null,
          completion_json text not null default '{}', verification_json text not null default '{}',
          result_json text not null default '{}', created_at real not null, updated_at real not null);
        create table if not exists dependencies (task_id text not null, depends_on text not null, primary key(task_id,depends_on));
        create table if not exists audit (
          id integer primary key autoincrement, at real not null, kind text not null,
          worker_id text, task_id text, detail_json text not null);
        """)
        columns = {row[1] for row in self.conn.execute("pragma table_info(workers)")}
        if "parent_id" not in columns:
            self.conn.execute("alter table workers add column parent_id text")
        self.conn.commit()

    def _audit(self, kind: str, worker_id: str | None = None, task_id: str | None = None, **detail) -> None:
        self.conn.execute("insert into audit(at,kind,worker_id,task_id,detail_json) values(?,?,?,?,?)",
                          (time.time(), kind, worker_id, task_id, json.dumps(detail, sort_keys=True)))

    @staticmethod
    def _decode(row: dict, fields: tuple[str, ...]) -> dict:
        for field in fields:
            if row.get(field) is not None:
                row[field] = json.loads(row[field])
        return row

    def create_worker(self, name: str, role: str, agent_type: str, worker_id: str | None = None,
                      parent_id: str | None = None) -> dict:
        now = time.time()
        worker_id = worker_id or f"wrk_{uuid.uuid4().hex}"
        if parent_id:
            self.worker(parent_id)
        self.conn.execute("insert into workers(id,name,role,agent_type,parent_id,state,last_activity,created_at,updated_at) values(?,?,?,?,?,?,?,?,?)",
                          (worker_id, name, role, agent_type, parent_id, "starting", now, now, now))
        self._audit("worker_created", worker_id, name=name, role=role, agent_type=agent_type, parent_id=parent_id)
        self.conn.commit()
        return self.worker(worker_id)

    def worker(self, worker_id: str) -> dict:
        row = self.conn.execute("select * from workers where id=?", (worker_id,)).fetchone()
        if not row:
            raise KeyError(worker_id)
        return self._decode(dict(row), ("ref_json", "topology_json", "health_json"))

    def workers(self) -> list[dict]:
        return [self._decode(dict(row), ("ref_json", "topology_json", "health_json"))
                for row in self.conn.execute("select * from workers order by created_at")]

    def update_worker(self, worker_id: str, *, state: str | None = None, ref: dict | None = None,
                      topology: dict | None = None, task_id: str | None = None, health: dict | None = None) -> dict:
        current = self.worker(worker_id)
        if state and state != current["state"] and (state not in STATES or state not in ALLOWED[current["state"]]):
            raise ValueError(f"invalid worker transition {current['state']} -> {state}")
        values = {
            "state": state or current["state"],
            "ref_json": json.dumps(ref if ref is not None else current["ref_json"]),
            "topology_json": json.dumps(topology if topology is not None else current["topology_json"]),
            "task_id": task_id if task_id is not None else current["task_id"],
            "health_json": json.dumps(health if health is not None else current["health_json"]),
            "last_activity": time.time(), "updated_at": time.time(),
        }
        self.conn.execute("update workers set state=:state,ref_json=:ref_json,topology_json=:topology_json,task_id=:task_id,health_json=:health_json,last_activity=:last_activity,updated_at=:updated_at where id=:id",
                          {**values, "id": worker_id})
        self._audit("worker_updated", worker_id, state=values["state"])
        self.conn.commit()
        return self.worker(worker_id)

    def create_task(self, title: str, parent_id: str | None = None, completion: dict | None = None, verification: dict | None = None) -> dict:
        now = time.time()
        task_id = f"tsk_{uuid.uuid4().hex}"
        self.conn.execute("insert into tasks(id,title,parent_id,state,completion_json,verification_json,result_json,created_at,updated_at) values(?,?,?,?,?,?,?,?,?)",
                          (task_id, title, parent_id, "ready", json.dumps(completion or {}), json.dumps(verification or {}), "{}", now, now))
        self._audit("task_created", task_id=task_id, title=title)
        self.conn.commit()
        return self.task(task_id)

    def task(self, task_id: str) -> dict:
        row = self.conn.execute("select * from tasks where id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        return self._decode(dict(row), ("completion_json", "verification_json", "result_json"))

    def tasks(self) -> list[dict]:
        return [self._decode(dict(row), ("completion_json", "verification_json", "result_json"))
                for row in self.conn.execute("select * from tasks order by created_at")]

    def dependencies(self, task_id: str) -> list[str]:
        self.task(task_id)
        return [row[0] for row in self.conn.execute(
            "select depends_on from dependencies where task_id=? order by depends_on", (task_id,))]

    def assign(self, task_id: str, worker_id: str) -> dict:
        self.worker(worker_id)
        self.task(task_id)
        if not self.ready_for_work(task_id):
            raise ValueError("task dependencies are not complete")
        self.conn.execute("update tasks set owner_id=?,state='working',updated_at=? where id=?", (worker_id, time.time(), task_id))
        self.update_worker(worker_id, state="working", task_id=task_id)
        self._audit("task_assigned", worker_id, task_id)
        self.conn.commit()
        return self.task(task_id)

    def reassign(self, task_id: str, worker_id: str) -> dict:
        prior = self.task(task_id).get("owner_id")
        if prior and prior != worker_id:
            old = self.worker(prior)
            if old["state"] not in TERMINAL_STATES:
                self.update_worker(prior, state="ready", task_id="")
        self._audit("task_reassigned", worker_id, task_id, previous_owner=prior)
        return self.assign(task_id, worker_id)

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        if task_id == depends_on:
            raise ValueError("task cannot depend on itself")
        self.task(task_id)
        self.task(depends_on)
        self.conn.execute("insert or ignore into dependencies(task_id,depends_on) values(?,?)", (task_id, depends_on))
        self._audit("dependency_added", task_id=task_id, depends_on=depends_on)
        self.conn.commit()

    def ready_for_work(self, task_id: str) -> bool:
        rows = self.conn.execute("select state from tasks where id in (select depends_on from dependencies where task_id=?)", (task_id,))
        return all(row[0] == "done" for row in rows)

    def complete_task(self, task_id: str, result: dict, verified: bool) -> dict:
        state = "done" if verified else "reviewing"
        self.conn.execute("update tasks set state=?,result_json=?,updated_at=? where id=?", (state, json.dumps(result), time.time(), task_id))
        task = self.task(task_id)
        if task["owner_id"]:
            worker = self.worker(task["owner_id"])
            if worker["state"] not in TERMINAL_STATES:
                self.update_worker(worker["id"], state="ready", task_id="")
        self._audit("task_completed" if verified else "task_review_required", task_id=task_id, result=result)
        self.conn.commit()
        return self.task(task_id)

    def record_retry(self, worker_id: str, reason: str) -> dict:
        worker = self.worker(worker_id)
        retries = worker["retries"] + 1
        self.conn.execute("update workers set retries=?,updated_at=?,last_activity=? where id=?",
                          (retries, time.time(), time.time(), worker_id))
        self._audit("worker_retry", worker_id, reason=reason, retries=retries)
        self.conn.commit()
        return self.worker(worker_id)

    def set_task_state(self, task_id: str, state: str, detail: dict | None = None) -> dict:
        if state not in {"ready", "working", "blocked", "reviewing", "done", "failed"}:
            raise ValueError(f"invalid task state {state}")
        self.task(task_id)
        self.conn.execute("update tasks set state=?,updated_at=? where id=?", (state, time.time(), task_id))
        self._audit("task_state", task_id=task_id, state=state, detail=detail or {})
        self.conn.commit()
        return self.task(task_id)

    def audit(self) -> list[dict]:
        return [self._decode(dict(row), ("detail_json",)) for row in self.conn.execute("select * from audit order by id")]

    def close(self) -> None:
        self.conn.close()
