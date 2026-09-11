#!/usr/bin/env python3
"""Disposable real-Windows-Terminal acceptance for MAIN-to-worker orchestration.

Run one layout at a time to keep every invocation below constrained shell
budgets.  It creates a fresh named Terminal window and isolated SQLite DB, then
only ever terminates its certificate-bound members via ``close_team``.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

from agent_identity import TargetError, reference_for_pid
from orchestrator import Orchestrator
from terminal_control import ensure_window_area
from terminal_topology import enumerate_topology
from worker_runtime import terminate_worker


ROLES = ("frontend", "backend", "reviewer", "qa", "docs", "ops")


def phase(name: str) -> None:
    print(json.dumps({"phase": name}), flush=True)


def foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow())


def wait_for(condition, timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.15)
    raise AssertionError(message)


def assert_balanced(workers: list[dict], bounds: dict[str, list[float] | tuple[float, ...]]) -> dict:
    rectangles = [bounds[worker["topology_json"]["pane"]["runtime_id"]] for worker in workers]
    widths = [rect[2] for rect in rectangles]
    heights = [rect[3] for rect in rectangles]
    if min(widths) <= 0 or min(heights) <= 0:
        raise AssertionError(f"non-positive pane geometry: {rectangles}")
    # The requested layouts are constructed as equal worker cells.  UIA returns
    # pixels, so allow a small divider/rounding margin rather than comparing the
    # split tree or source code.
    if len(widths) > 1 and max(widths) - min(widths) > max(widths) * 0.06:
        raise AssertionError(f"worker widths did not converge: rectangles={rectangles} widths={widths}")
    if len(heights) > 1 and max(heights) - min(heights) > max(heights) * 0.06:
        raise AssertionError(f"worker heights did not converge: rectangles={rectangles} heights={heights}")
    return {"widths": widths, "heights": heights}


def process_is_gone(pid: int) -> bool:
    try:
        reference_for_pid(pid)
    except (TargetError, OSError):
        return True
    return False


def run(worker_count: int, stage: str = "full") -> dict:
    if worker_count not in {1, 2, 3, 4, 6}:
        raise ValueError("worker count must be one of 1, 2, 3, 4, 6")
    run_id = uuid.uuid4().hex
    roles = list(ROLES[:worker_count])
    os.environ["AGENT_ORCHESTRATION_DB"] = str(Path(tempfile.gettempdir()) / f"orch-live-{run_id}.db")
    control = Orchestrator()
    main: dict | None = None
    prior_window = 0
    before_pids: list[int] = []
    evidence: dict = {"run": run_id, "workers": worker_count}
    try:
        phase("spawn-main")
        main = control.spawn(f"accept-main-{run_id[-8:]}", "controller", cwd=str(ROOT))
        before_pids.append(main["ref_json"]["pid"])
        # A default-sized window makes a 2x2/2x3 worker grid one text row tall,
        # which is a console too short to run a command.  Grow the window we own
        # (without maximizing to fullscreen or stealing focus) so every worker
        # pane has workable height before the team is built.
        ensure_window_area(control.refresh(main["id"])["topology_json"]["window"]["hwnd"])
        time.sleep(0.4)
        phase("prepare-foreground")
        prior_window = foreground_window()
        evidence["foreground_before"] = prior_window
        evidence["foreground"] = "checked" if prior_window else "unobservable_no_foreground_window"

        phase("create-team")
        created = control.team(main["id"], roles, agent_type="powershell", cwd=str(ROOT))
        workers = created["workers"]
        before_pids.extend(worker["ref_json"]["pid"] for worker in workers)
        if prior_window:
            wait_for(lambda: foreground_window() == prior_window, 5, "split creation did not restore the foreground window")
        main_after = control.store.worker(main["id"])
        if main_after["ref_json"]["pid"] != main["ref_json"]["pid"]:
            raise AssertionError("MAIN PID changed while creating workers")
        if main_after["topology_json"]["certificate"] not in control.store.worker(main["id"])["ref_json"]["command_line"]:
            raise AssertionError("MAIN certificate is no longer bound to its process")
        evidence["geometry"] = assert_balanced(workers, created["layout"]["bounds"])
        if stage == "layout":
            evidence["status"] = "PASS"
            return evidence

        phase("route-work")
        frontend_token = f"FRONTEND_{run_id}"
        frontend_task = control.create_task("frontend implementation")
        frontend_delivery = control.dispatch_role("frontend", frontend_task["id"], f"Write-Output '{frontend_token}'")
        frontend_verified = control.verify_task(frontend_task["id"], frontend_token)
        if frontend_delivery["delivery"]["phase"] != "COMMAND_EXECUTED" or not frontend_verified["verified"]:
            raise AssertionError("frontend route was not explicitly delivered and verified")

        if worker_count >= 2:
            backend_token = f"BACKEND_{run_id}"
            backend_task = control.create_task("backend implementation")
            backend_delivery = control.dispatch_role("backend", backend_task["id"], f"Write-Output '{backend_token}'")
            backend_verified = control.verify_task(backend_task["id"], backend_token)
            if backend_delivery["delivery"]["phase"] != "COMMAND_EXECUTED" or not backend_verified["verified"]:
                raise AssertionError("backend route was not explicitly delivered and verified")

        if worker_count >= 3:
            review_task = control.create_task("review and correction")
            control.dispatch_role("frontend", review_task["id"], f"Write-Output 'CANDIDATE_{run_id}'")
            handoff = control.handoff_role("frontend", "reviewer", review_task["id"], f"Write-Output 'REJECTED_{run_id}'")
            rejected = control.verify_task(review_task["id"], f"APPROVED_{run_id}", control.worker_by_role("reviewer")["id"])
            if handoff["delivery"]["phase"] != "COMMAND_EXECUTED" or rejected["verified"] or rejected["task"]["state"] != "reviewing":
                raise AssertionError("review rejection was not represented as a correction-required state")
            corrected = control.dispatch_role("reviewer", review_task["id"], f"Write-Output 'APPROVED_{run_id}'")
            approved = control.verify_task(review_task["id"], f"APPROVED_{run_id}", control.worker_by_role("reviewer")["id"])
            if corrected["delivery"]["phase"] != "COMMAND_EXECUTED" or not approved["verified"]:
                raise AssertionError("review correction was not explicitly verified")
            evidence["review"] = "rejected_then_corrected"

        phase("recover-worker")
        recovered_target = workers[-1]
        old_pid = recovered_target["ref_json"]["pid"]
        control.store.update_worker(recovered_target["id"], state="failed",
                                    health={"reachable": False, "reason": "acceptance recovery"})
        recovered = control.recover(recovered_target["id"])
        if recovered["ref_json"]["pid"] != old_pid or recovered["topology_json"]["window_name"] != main_after["topology_json"]["window_name"]:
            raise AssertionError("in-place recovery did not preserve the certified worker transport")
        recovery_task = control.create_task("post-recovery probe")
        recovery_token = f"RECOVERED_{run_id}"
        recovery_delivery = control.dispatch_role(recovered_target["role"], recovery_task["id"], f"Write-Output '{recovery_token}'")
        if recovery_delivery["delivery"]["phase"] != "COMMAND_EXECUTED" or not control.verify_task(recovery_task["id"], recovery_token)["verified"]:
            raise AssertionError("recovered worker did not accept and verify new work")
        evidence["recovery"] = {"pid": recovered["ref_json"]["pid"], "mode": "in_place_transport"}

        after_recovery = [control.store.worker(worker["id"]) for worker in workers]
        current_bounds = created["layout"]["bounds"]
        # Recovery normalizes again, so measure from its fresh topology instead
        # of trusting the stale initial result.
        from layout_normalizer import measured
        current_bounds = measured(control.store.worker(main["id"])["topology_json"])
        evidence["recovered_geometry"] = assert_balanced(after_recovery, current_bounds)

        phase("close-team")
        closed = control.close_team(main["id"])
        evidence["teardown"] = closed
        all_pids = [control.store.worker(worker["id"])["ref_json"].get("pid") for worker in [control.store.worker(main["id"]), *after_recovery]]
        wait_for(lambda: all(process_is_gone(pid) for pid in all_pids if pid), 10, "owned worker process leaked after team close")
        hwnd = main_after["topology_json"]["window"]["hwnd"]
        snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd])
        certificates = {control.store.worker(worker["id"])["topology_json"].get("certificate") for worker in [control.store.worker(main["id"]), *after_recovery]}
        if any(pane["title"] in certificates for pane in snapshot["panes"]):
            raise AssertionError("owned pane leaked after exact team close")
        evidence["status"] = "PASS"
        return evidence
    finally:
        phase("cleanup")
        if main:
            try:
                active = [worker for worker in control._team_members(main["id"])
                          if worker["state"] not in {"failed", "done", "disconnected"}]
                if active:
                    control.close_team(main["id"])
            except Exception:
                # Cleanup fallback still uses only the bridge's exact certificate-bound PIDs.
                for worker in control._team_members(main["id"]):
                    if worker["state"] not in {"failed", "done", "disconnected"}:
                        try:
                            terminate_worker(control.store, worker["id"])
                        except Exception:
                            pass
        control.store.close()
        Path(os.environ["AGENT_ORCHESTRATION_DB"]).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--stage", choices=("layout", "full"), default="full")
    args = parser.parse_args()
    print(json.dumps(run(args.workers, args.stage), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
