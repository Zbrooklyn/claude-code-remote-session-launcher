#!/usr/bin/env python3
"""Durable, bridge-owned multi-worker orchestration CLI.

This intentionally composes V1 identity/console control rather than creating
another terminal manager.  Every mutating call resolves a current AgentRef
before writing, and every PowerShell dispatch appends an operation marker that
must be observed from that exact console.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid

from orchestration_store import Store
from terminal_control import close_exact_tab
from worker_runtime import (
    WorkerRuntimeError,
    read_worker,
    refresh_worker_topology,
    restart_worker,
    send_worker,
    spawn_worker,
    terminate_worker,
)


class OrchestrationError(RuntimeError):
    pass


def _op_id() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


class Orchestrator:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def spawn(self, name: str, role: str, engine: str = "powershell.exe",
              parent: str | None = None, agent_type: str = "powershell") -> dict:
        return spawn_worker(self.store, name, role, engine, parent, agent_type)

    def refresh(self, worker_id: str) -> dict:
        return refresh_worker_topology(self.store, worker_id)

    def create_task(self, title: str, parent: str | None = None,
                    completion: dict | None = None, verification: dict | None = None) -> dict:
        return self.store.create_task(title, parent, completion, verification)

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        self.store.add_dependency(task_id, depends_on)

    def dispatch(self, worker_id: str, task_id: str, command: str) -> dict:
        if not self.store.ready_for_work(task_id):
            raise OrchestrationError("DEPENDENCIES_PENDING")
        self.refresh(worker_id)
        self.store.assign(task_id, worker_id)
        op_id = _op_id()
        marker = f"ORCH_RESULT_{op_id}"
        # This is input to the shell, not a wt commandline.  The marker after
        # the instruction proves execution rather than merely input queuing.
        try:
            result = send_worker(self.store, worker_id, f"{command}; Write-Output '{marker}'", marker)
        except Exception as exc:
            self.store.set_task_state(task_id, "blocked", {"operation": op_id, "error": str(exc)})
            raise OrchestrationError(f"DELIVERY_FAILED: {exc}") from exc
        if result["phase"] != "COMMAND_EXECUTED":
            self.store.set_task_state(task_id, "blocked", {"operation": op_id, "phase": result["phase"]})
            raise OrchestrationError(f"DELIVERY_UNVERIFIED: {result['phase']}")
        self.store._audit("operation_executed", worker_id, task_id, operation_id=op_id, marker=marker)
        self.store.conn.commit()
        return {"operation_id": op_id, "marker": marker, "delivery": result}

    def handoff(self, source_worker: str, destination_worker: str, task_id: str, command: str) -> dict:
        result = self.dispatch(destination_worker, task_id, command)
        self.store._audit("worker_handoff", source_worker, task_id,
                          destination_worker=destination_worker, operation_id=result["operation_id"])
        self.store.conn.commit()
        return result

    def verify_task(self, task_id: str, required_text: str, reviewer_id: str | None = None) -> dict:
        task = self.store.task(task_id)
        owner = task.get("owner_id")
        if not owner:
            raise OrchestrationError("TASK_HAS_NO_OWNER")
        screen = read_worker(self.store, owner)["screen"]
        verified = required_text in screen
        result = {"required_text": required_text, "observed": verified, "reviewer_id": reviewer_id}
        self.store.complete_task(task_id, result, verified)
        if reviewer_id:
            reviewer = self.store.worker(reviewer_id)
            self.store._audit("reviewer_verification", reviewer["id"], task_id,
                              required_text=required_text, observed=verified)
            self.store.conn.commit()
        return {"verified": verified, "result": result, "task": self.store.task(task_id)}

    def monitor(self, worker_id: str) -> dict:
        worker = self.store.worker(worker_id)
        try:
            self.refresh(worker_id)
            screen = read_worker(self.store, worker_id)["screen"]
        except Exception as exc:
            current = self.store.worker(worker_id)
            if current["state"] not in {"failed", "done", "disconnected"}:
                self.store.update_worker(worker_id, state="disconnected",
                                         health={"reachable": False, "reason": str(exc)})
            return {"worker_id": worker_id, "state": "disconnected", "reason": str(exc)}
        fingerprint = hashlib.sha256(screen.encode(errors="replace")).hexdigest()
        previous = (worker.get("health_json") or {}).get("screen_fingerprint")
        changed = fingerprint != previous
        current = self.store.worker(worker_id)
        health = {**(current.get("health_json") or {}), "reachable": True,
                  "screen_fingerprint": fingerprint, "screen_changed": changed,
                  "observed_at": time.time()}
        self.store.update_worker(worker_id, health=health)
        return {"worker_id": worker_id, "state": self.store.worker(worker_id)["state"],
                "screen_changed": changed, "quiescent": not changed,
                "completion": "UNPROVEN"}

    def wait(self, worker_ids: list[str], mode: str = "all", timeout: float = 30, poll: float = 0.25) -> dict:
        if mode not in {"all", "any"}:
            raise OrchestrationError("WAIT_MODE_MUST_BE_ALL_OR_ANY")
        deadline = time.monotonic() + timeout
        observations: dict[str, dict] = {}
        while time.monotonic() < deadline:
            observations = {worker_id: self.monitor(worker_id) for worker_id in worker_ids}
            ready = [x for x in observations.values() if x["state"] in {"ready", "waiting", "done"}]
            if (mode == "all" and len(ready) == len(worker_ids)) or (mode == "any" and ready):
                return {"phase": "WORKERS_QUIESCENT", "mode": mode, "workers": observations}
            time.sleep(poll)
        return {"phase": "TIMEOUT", "mode": mode, "workers": observations}

    def recover(self, worker_id: str, engine: str = "powershell.exe", max_retries: int = 2) -> dict:
        worker = self.store.worker(worker_id)
        if worker["retries"] >= max_retries:
            raise OrchestrationError("RETRY_LIMIT_REACHED")
        if worker["state"] not in {"failed", "disconnected"}:
            try:
                self.refresh(worker_id)
                return self.store.worker(worker_id)
            except WorkerRuntimeError:
                pass
        return restart_worker(self.store, worker_id, engine)

    def close(self, worker_id: str) -> None:
        """Close an owned dedicated tab only after exact worker termination.

        A pane-local close action is not trusted on this Terminal build.  For a
        shared tab, callers must close siblings first; this avoids a console
        wide or visually ambiguous close.
        """
        worker = self.store.worker(worker_id)
        topology = worker.get("topology_json") or {}
        tab_id = (topology.get("tab") or {}).get("bridge_id")
        siblings = [x for x in self.store.workers()
                    if x["id"] != worker_id and (x.get("topology_json") or {}).get("tab", {}).get("bridge_id") == tab_id
                    and x["state"] not in {"failed", "done", "disconnected"}]
        if siblings:
            raise OrchestrationError("REFUSE_SHARED_TAB_CLOSE")
        if worker["state"] not in {"failed", "done", "disconnected"}:
            terminate_worker(self.store, worker_id)
        close_exact_tab(topology)


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("spawn"); p.add_argument("name"); p.add_argument("role"); p.add_argument("--engine", default="powershell.exe"); p.add_argument("--parent"); p.add_argument("--agent-type", default="powershell")
    p = sub.add_parser("task-create"); p.add_argument("title"); p.add_argument("--parent")
    p = sub.add_parser("depends"); p.add_argument("task"); p.add_argument("dependency")
    p = sub.add_parser("dispatch"); p.add_argument("worker"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("handoff"); p.add_argument("source"); p.add_argument("destination"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("verify"); p.add_argument("task"); p.add_argument("text"); p.add_argument("--reviewer")
    p = sub.add_parser("monitor"); p.add_argument("worker")
    p = sub.add_parser("recover"); p.add_argument("worker"); p.add_argument("--engine", default="powershell.exe")
    p = sub.add_parser("close"); p.add_argument("worker")
    sub.add_parser("workers"); sub.add_parser("tasks"); sub.add_parser("audit")
    args = parser.parse_args(argv)
    control = Orchestrator()
    try:
        if args.command == "spawn": out = control.spawn(args.name, args.role, args.engine, args.parent, args.agent_type)
        elif args.command == "task-create": out = control.create_task(args.title, args.parent)
        elif args.command == "depends": control.add_dependency(args.task, args.dependency); out = {"ok": True}
        elif args.command == "dispatch": out = control.dispatch(args.worker, args.task, args.instruction)
        elif args.command == "handoff": out = control.handoff(args.source, args.destination, args.task, args.instruction)
        elif args.command == "verify": out = control.verify_task(args.task, args.text, args.reviewer)
        elif args.command == "monitor": out = control.monitor(args.worker)
        elif args.command == "recover": out = control.recover(args.worker, args.engine)
        elif args.command == "close": control.close(args.worker); out = {"ok": True}
        elif args.command == "workers": out = control.store.workers()
        elif args.command == "tasks": out = control.store.tasks()
        else: out = control.store.audit()
        _json(out); return 0
    except (OrchestrationError, WorkerRuntimeError, ValueError, KeyError) as exc:
        _json({"ok": False, "error": str(exc)}); return 1


if __name__ == "__main__":
    raise SystemExit(main())
