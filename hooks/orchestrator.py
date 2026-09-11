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
from terminal_control import close_exact_tab, close_pane_and_verify
from terminal_topology import enumerate_topology
from worker_runtime import (
    WorkerRuntimeError,
    adopt_main,
    read_worker,
    refresh_worker_topology,
    restart_worker,
    send_worker,
    send_worker_input,
    spawn_worker,
    terminate_worker,
)
from team_layout import create_workers, normalize_main_and_workers


class OrchestrationError(RuntimeError):
    pass


def _op_id() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


class Orchestrator:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()

    def spawn(self, name: str, role: str, engine: str = "powershell.exe",
              parent: str | None = None, agent_type: str = "powershell",
              cwd: str | None = None, direction: str = "right") -> dict:
        return spawn_worker(self.store, name, role, engine, parent, agent_type, cwd, direction)

    def refresh(self, worker_id: str) -> dict:
        return refresh_worker_topology(self.store, worker_id)

    def adopt_main(self, name: str, pid: int, agent_type: str = "claude") -> dict:
        """Certify an already-running pane host (e.g. this Claude session) as MAIN."""
        return adopt_main(self.store, name, int(pid), agent_type)

    def team(self, main_id: str, roles: list[str], engine: str = "powershell.exe",
             agent_type: str = "claude", cwd: str | None = None,
             agent_command: str | None = None) -> dict:
        """Create named workers below a preserved bridge-owned MAIN."""
        main=self.store.worker(main_id)
        if main["role"] != "controller":
            raise OrchestrationError("MAIN_MUST_BE_A_CONTROLLER_WORKER")
        workers=create_workers(self.store, main_id, roles, engine, agent_type, cwd, agent_command)
        layout=normalize_main_and_workers(self.store, main_id, [w["id"] for w in workers])
        return {"main_id":main_id,"workers":[self.store.worker(w["id"]) for w in workers],"layout":layout}

    def worker_by_role(self, role: str) -> dict:
        matches=[w for w in self.store.workers() if w["role"].lower()==role.lower() and w["state"] not in {"failed","disconnected"}]
        if len(matches)!=1: raise OrchestrationError(f"ROLE_NOT_UNIQUE: {role}")
        return matches[0]

    def create_task(self, title: str, parent: str | None = None,
                    completion: dict | None = None, verification: dict | None = None) -> dict:
        return self.store.create_task(title, parent, completion, verification)

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        self.store.add_dependency(task_id, depends_on)

    def dispatch(self, worker_id: str, task_id: str, command: str, *, reassign: bool = False) -> dict:
        if not self.store.ready_for_work(task_id):
            raise OrchestrationError("DEPENDENCIES_PENDING")
        self.refresh(worker_id)
        if reassign:
            self.store.reassign(task_id, worker_id)
        else:
            self.store.assign(task_id, worker_id)
        op_id = _op_id()
        agent_type = self.store.worker(worker_id)["agent_type"].lower()
        marker = f"ORCH_RESULT_{op_id}" if agent_type == "powershell" else None
        try:
            if agent_type == "powershell":
                # This is input to the shell, not a wt commandline. The marker
                # after the instruction proves execution rather than queuing.
                result = send_worker(self.store, worker_id, f"{command}; Write-Output '{marker}'", marker)
            else:
                result = send_worker_input(self.store, worker_id, command)
        except Exception as exc:
            self.store.set_task_state(task_id, "blocked", {"operation": op_id, "error": str(exc)})
            raise OrchestrationError(f"DELIVERY_FAILED: {exc}") from exc
        expected_phase = "COMMAND_EXECUTED" if marker else "INPUT_OBSERVED"
        if result["phase"] != expected_phase:
            self.store.set_task_state(task_id, "blocked", {"operation": op_id, "phase": result["phase"]})
            raise OrchestrationError(f"DELIVERY_UNVERIFIED: {result['phase']}")
        self.store._audit("operation_executed" if marker else "agent_input_observed",
                          worker_id, task_id, operation_id=op_id, marker=marker)
        self.store.conn.commit()
        return {"operation_id": op_id, "marker": marker, "delivery": result}

    def handoff(self, source_worker: str, destination_worker: str, task_id: str, command: str) -> dict:
        if self.store.task(task_id).get("owner_id") != source_worker:
            raise OrchestrationError("HANDOFF_SOURCE_DOES_NOT_OWN_TASK")
        result = self.dispatch(destination_worker, task_id, command, reassign=True)
        self.store._audit("worker_handoff", source_worker, task_id,
                          destination_worker=destination_worker, operation_id=result["operation_id"])
        self.store.conn.commit()
        return result

    def dispatch_role(self, role: str, task_id: str, command: str) -> dict:
        """Route a task through the unique currently-live worker for a role."""
        return self.dispatch(self.worker_by_role(role)["id"], task_id, command)

    def handoff_role(self, source_role: str, destination_role: str, task_id: str, command: str) -> dict:
        source = self.worker_by_role(source_role)
        destination = self.worker_by_role(destination_role)
        return self.handoff(source["id"], destination["id"], task_id, command)

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
        recovered = restart_worker(self.store, worker_id, engine)
        main_id = self._controller_root(recovered["id"])
        if main_id:
            members = [member["id"] for member in self._team_members(main_id)
                       if member["id"] != main_id and member["state"] not in {"failed", "done", "disconnected"}]
            if members:
                normalize_main_and_workers(self.store, main_id, members)
        return self.store.worker(worker_id)

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

    def _team_members(self, main_id: str) -> list[dict]:
        main = self.store.worker(main_id)
        if main["role"] != "controller":
            raise OrchestrationError("MAIN_MUST_BE_A_CONTROLLER_WORKER")
        workers = {worker["id"]: worker for worker in self.store.workers()}
        members = []
        for worker in workers.values():
            current = worker
            seen: set[str] = set()
            while current["id"] not in seen:
                if current["id"] == main_id:
                    members.append(worker)
                    break
                seen.add(current["id"])
                parent_id = current.get("parent_id")
                if not parent_id or parent_id not in workers:
                    break
                current = workers[parent_id]
        return members

    def _controller_root(self, worker_id: str) -> str | None:
        current = self.store.worker(worker_id)
        seen: set[str] = set()
        while current["id"] not in seen:
            if current["role"] == "controller":
                return current["id"]
            seen.add(current["id"])
            parent_id = current.get("parent_id")
            if not parent_id:
                return None
            current = self.store.worker(parent_id)
        raise OrchestrationError("WORKER_PARENT_CYCLE")

    def _close_adopted_team(self, main: dict, members: list[dict]) -> dict:
        """Tear down workers under an adopted MAIN; MAIN's process and tab stay.

        The tab is proven owned when it holds exactly MAIN's pane plus every
        member's certificate pane and nothing else.  Workers are then stopped
        by exact certificate-bound PID and their panes closed one by one.
        """
        main = refresh_worker_topology(self.store, main["id"])
        workers = [worker for worker in members if worker["id"] != main["id"]]
        hwnd = main["topology_json"]["window"]["hwnd"]
        if any((worker.get("topology_json") or {}).get("window", {}).get("hwnd") != hwnd for worker in workers):
            raise OrchestrationError("REFUSE_TEAM_ACROSS_WINDOWS")
        snapshot = enumerate_topology(exhaustive=False, hwnds=[hwnd])
        tab_id = main["topology_json"]["pane"]["tab_id"] if "tab_id" in main["topology_json"]["pane"] \
            else main["topology_json"]["tab"]["bridge_id"]
        tab_panes = {pane["runtime_id"]: pane for pane in snapshot["panes"] if pane["tab_id"] == tab_id}
        expected = {main["topology_json"]["pane"]["runtime_id"]}
        closable: list[dict] = []
        for worker in workers:
            if worker["state"] in {"failed", "done", "disconnected"} and not worker.get("topology_json"):
                continue
            certificate = worker["topology_json"]["certificate"]
            matches = [pane for pane in tab_panes.values() if pane.get("title") == certificate]
            if len(matches) != 1:
                raise OrchestrationError("REFUSE_TEAM_CERTIFICATE_PANE")
            expected.add(matches[0]["runtime_id"])
            closable.append({**worker["topology_json"], "pane": matches[0], "window": main["topology_json"]["window"]})
        if set(tab_panes) != expected:
            raise OrchestrationError("REFUSE_TEAM_TAB_WITH_FOREIGN_PANE")
        stopped = []
        for worker in workers:
            if worker["state"] not in {"failed", "done", "disconnected"}:
                terminate_worker(self.store, worker["id"])
                stopped.append(worker["id"])
        for topology in closable:
            close_pane_and_verify(topology)
        self.store._audit("team_closed", main["id"], members=[worker["id"] for worker in workers],
                          stopped=stopped, main_preserved=True)
        self.store.conn.commit()
        return {"main_id": main["id"], "closed": len(closable), "stopped": stopped, "main_preserved": True}

    def close_team(self, main_id: str) -> dict:
        """Stop and close a certified team tab, refusing unmanaged sibling panes."""
        members = self._team_members(main_id)
        if not members:
            raise OrchestrationError("TEAM_NOT_FOUND")
        main = self.store.worker(main_id)
        if (main.get("topology_json") or {}).get("adopted"):
            return self._close_adopted_team(main, members)
        anchor = next((worker for worker in members if worker.get("topology_json")), None)
        if not anchor:
            raise OrchestrationError("TEAM_TOPOLOGY_UNAVAILABLE")
        topology = anchor["topology_json"]
        if any(not (worker.get("topology_json") or {}).get("certificate") for worker in members):
            raise OrchestrationError("TEAM_CERTIFICATE_UNAVAILABLE")
        hwnd = topology["window"]["hwnd"]
        if any((worker["topology_json"]["window"].get("hwnd") != hwnd) for worker in members):
            raise OrchestrationError("REFUSE_TEAM_ACROSS_WINDOWS")
        snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd])
        current_panes = {}
        for worker in members:
            certificate = worker["topology_json"]["certificate"]
            matches = [pane for pane in snapshot["panes"] if pane.get("title") == certificate]
            if len(matches) != 1:
                raise OrchestrationError("REFUSE_TEAM_CERTIFICATE_PANE")
            current_panes[worker["id"]] = matches[0]
        tab_ids = {pane["tab_id"] for pane in current_panes.values()}
        if len(tab_ids) != 1:
            raise OrchestrationError("REFUSE_TEAM_ACROSS_TABS")
        tab_id = next(iter(tab_ids))
        actual = {pane["runtime_id"] for pane in snapshot["panes"] if pane["tab_id"] == tab_id}
        expected = {pane["runtime_id"] for pane in current_panes.values()}
        if actual != expected:
            raise OrchestrationError("REFUSE_TEAM_TAB_WITH_FOREIGN_PANE")
        tabs = [tab for tab in snapshot["tabs"] if tab["bridge_id"] == tab_id]
        if len(tabs) != 1:
            raise OrchestrationError("REFUSE_TEAM_TAB_UNRESOLVED")
        close_topology = {**topology, "tab": tabs[0], "pane": current_panes[anchor["id"]]}
        stopped = []
        for worker in members:
            if worker["state"] not in {"failed", "done", "disconnected"}:
                terminate_worker(self.store, worker["id"])
                stopped.append(worker["id"])
        close_exact_tab(close_topology)
        self.store._audit("team_closed", main_id, members=[worker["id"] for worker in members], stopped=stopped)
        self.store.conn.commit()
        return {"main_id": main_id, "closed": len(members), "stopped": stopped}


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("spawn"); p.add_argument("name"); p.add_argument("role"); p.add_argument("--engine", default="powershell.exe"); p.add_argument("--parent"); p.add_argument("--agent-type", default="powershell"); p.add_argument("--cwd"); p.add_argument("--direction", choices=("left", "right", "up", "down"), default="right")
    p = sub.add_parser("adopt-main"); p.add_argument("name"); p.add_argument("pid", type=int); p.add_argument("--agent-type", choices=("powershell", "claude", "codex"), default="claude")
    p = sub.add_parser("team"); p.add_argument("main"); p.add_argument("roles", nargs="+"); p.add_argument("--engine", default="powershell.exe"); p.add_argument("--agent-type", choices=("powershell", "claude", "codex"), default="claude"); p.add_argument("--cwd"); p.add_argument("--agent-command", help="interactive command typed into each worker console (default: the agent type)")
    p = sub.add_parser("task-create"); p.add_argument("title"); p.add_argument("--parent")
    p = sub.add_parser("depends"); p.add_argument("task"); p.add_argument("dependency")
    p = sub.add_parser("dispatch"); p.add_argument("worker"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("dispatch-role"); p.add_argument("role"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("handoff"); p.add_argument("source"); p.add_argument("destination"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("handoff-role"); p.add_argument("source_role"); p.add_argument("destination_role"); p.add_argument("task"); p.add_argument("instruction")
    p = sub.add_parser("verify"); p.add_argument("task"); p.add_argument("text"); p.add_argument("--reviewer")
    p = sub.add_parser("monitor"); p.add_argument("worker")
    p = sub.add_parser("wait"); p.add_argument("workers", nargs="+"); p.add_argument("--mode", choices=("all", "any"), default="all"); p.add_argument("--timeout", type=float, default=30); p.add_argument("--poll", type=float, default=.25)
    p = sub.add_parser("recover"); p.add_argument("worker"); p.add_argument("--engine", default="powershell.exe")
    p = sub.add_parser("close"); p.add_argument("worker")
    p = sub.add_parser("close-team"); p.add_argument("main")
    sub.add_parser("workers"); sub.add_parser("tasks"); sub.add_parser("audit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    control = Orchestrator()
    try:
        if args.command == "spawn": out = control.spawn(args.name, args.role, args.engine, args.parent, args.agent_type, args.cwd, args.direction)
        elif args.command == "adopt-main": out = control.adopt_main(args.name, args.pid, args.agent_type)
        elif args.command == "team": out = control.team(args.main, args.roles, args.engine, args.agent_type, args.cwd, args.agent_command)
        elif args.command == "task-create": out = control.create_task(args.title, args.parent)
        elif args.command == "depends": control.add_dependency(args.task, args.dependency); out = {"ok": True}
        elif args.command == "dispatch": out = control.dispatch(args.worker, args.task, args.instruction)
        elif args.command == "dispatch-role": out = control.dispatch_role(args.role, args.task, args.instruction)
        elif args.command == "handoff": out = control.handoff(args.source, args.destination, args.task, args.instruction)
        elif args.command == "handoff-role": out = control.handoff_role(args.source_role, args.destination_role, args.task, args.instruction)
        elif args.command == "verify": out = control.verify_task(args.task, args.text, args.reviewer)
        elif args.command == "monitor": out = control.monitor(args.worker)
        elif args.command == "wait": out = control.wait(args.workers, args.mode, args.timeout, args.poll)
        elif args.command == "recover": out = control.recover(args.worker, args.engine)
        elif args.command == "close": control.close(args.worker); out = {"ok": True}
        elif args.command == "close-team": out = control.close_team(args.main)
        elif args.command == "workers": out = control.store.workers()
        elif args.command == "tasks": out = control.store.tasks()
        else: out = control.store.audit()
        _json(out); return 0
    except (OrchestrationError, WorkerRuntimeError, ValueError, KeyError) as exc:
        _json({"ok": False, "error": str(exc)}); return 1


if __name__ == "__main__":
    raise SystemExit(main())
