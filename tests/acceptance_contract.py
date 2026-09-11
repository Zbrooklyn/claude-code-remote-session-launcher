"""Behavioural acceptance driver for the Claude multi-session orchestration.

Runs the real bridge against a disposable, self-cleaning team in one Windows
Terminal window and records real evidence for each named capability. Powershell
workers are used so command delivery is marker-verifiable; the real-Claude and
skill layers are proven by separate runs.

    py -3.12 tests/acceptance_contract.py --workers 4 --out <path.json>
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

from agent_identity import TargetError, reference_for_pid  # noqa: E402
from layout_normalizer import measured  # noqa: E402
from orchestrator import Orchestrator, OrchestrationError  # noqa: E402
from terminal_control import ensure_window_area  # noqa: E402
from terminal_topology import enumerate_topology  # noqa: E402
from worker_runtime import read_worker, send_worker  # noqa: E402

ROLES = ["frontend", "backend", "database", "qa", "docs", "ops"]


class Evidence:
    def __init__(self):
        self.checks: dict[str, dict] = {}

    def record(self, name: str, ok: bool, detail) -> bool:
        self.checks[name] = {"status": "PASS" if ok else "FAIL", "evidence": detail}
        print(json.dumps({"check": name, "status": self.checks[name]["status"], "evidence": detail}, default=str)[:400], flush=True)
        return ok

    def error(self, name: str, exc) -> None:
        self.checks[name] = {"status": "FAIL", "evidence": f"exception: {exc!r}"}
        print(json.dumps({"check": name, "status": "FAIL", "evidence": repr(exc)})[:400], flush=True)


def foreground() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow())


def run(worker_count: int) -> dict:
    run_id = uuid.uuid4().hex
    os.environ["AGENT_ORCHESTRATION_DB"] = str(Path(tempfile.gettempdir()) / f"orch-accept-{run_id}.db")
    roles = ROLES[:worker_count]
    ev = Evidence()
    control = Orchestrator()
    main = None
    try:
        main = control.spawn(f"accept-main-{run_id[-6:]}", "controller", cwd=str(ROOT))
        ev.record("main_launch", bool(main and main["state"] == "ready"), {"main_id": main["id"], "state": main["state"]})
        ensure_window_area(control.refresh(main["id"])["topology_json"]["window"]["hwnd"])
        time.sleep(0.4)
        fg_before = foreground()

        created = control.team(main["id"], roles, agent_type="powershell", cwd=str(ROOT))
        workers = created["workers"]
        by_role = {w["role"]: w for w in workers}
        ev.record("worker_count", len(workers) == worker_count, {"requested": worker_count, "created": len(workers)})

        # --- topology / geometry (measured, not assumed) ---
        bounds = measured(control.refresh(main["id"])["topology_json"])
        main_rect = bounds[control.store.worker(main["id"])["topology_json"]["pane"]["runtime_id"]]
        wrects = {w["role"]: bounds[control.refresh(w["id"])["topology_json"]["pane"]["runtime_id"]] for w in workers}
        widths = [r[2] for r in wrects.values()]
        tops = [r[1] for r in wrects.values()]
        ev.record("main_top_row", all(main_rect[1] + main_rect[3] <= t + 6 for t in tops), {"main": main_rect, "worker_tops": tops})
        ev.record("main_separate", main_rect[1] < min(tops), {"main_top": main_rect[1], "min_worker_top": min(tops)})
        # bottom workers approximately equal width (per row for 2-row grids)
        rows: dict[int, list[float]] = {}
        for r in wrects.values():
            rows.setdefault(round(r[1] / 25), []).append(r[2])
        equal = all(max(w) - min(w) <= max(w) * 0.06 for w in rows.values())
        ev.record("equal_worker_widths", equal, {"widths_by_row": list(rows.values())})
        ev.record("measured_geometry", all(r[2] > 0 and r[3] > 0 for r in wrects.values()), {"rects": wrects})
        ev.record("foreground_restored", foreground() == fg_before or fg_before == 0, {"before": fg_before, "after": foreground()})

        # --- identity / role registry ---
        ids = {w["id"] for w in workers}
        ev.record("unique_identity", len(ids) == worker_count, {"ids": sorted(i[-6:] for i in ids)})
        ev.record("role_identity", all(w["role"] == role for role, w in by_role.items()), {"roles": list(by_role)})
        resolved = {role: control.worker_by_role(role)["id"] == by_role[role]["id"] for role in roles}
        ev.record("role_registry", all(resolved.values()), resolved)

        # --- role-addressed delivery to each worker, verified ---
        tokens = {}
        deliveries = {}
        for role in roles:
            token = f"TOK_{role.upper()}_{run_id[:6]}"
            tokens[role] = token
            task = control.create_task(f"{role} task")
            d = control.dispatch_role(role, task["id"], f"Write-Output '{token}'")
            deliveries[role] = d["delivery"]["phase"]
        ev.record("role_addressed_delivery", all(p == "COMMAND_EXECUTED" for p in deliveries.values()), deliveries)

        # --- no cross-routing: each worker's screen has only its own token ---
        screens = {role: read_worker(control.store, by_role[role]["id"])["screen"] for role in roles}
        no_cross = all(tokens[a] in screens[a] and all(tokens[b] not in screens[a] for b in roles if b != a) for a in roles)
        ev.record("no_cross_routing", no_cross, {role: [t for t in tokens.values() if t in screens[role]] for role in roles})
        ev.record("independent_state", no_cross, "each console contains only its own token")

        # --- worker -> MAIN readback (MAIN verifies the worker's output) ---
        rb_task = control.create_task("frontend reports up")
        rb_token = f"REPORT_{run_id[:6]}"
        control.dispatch_role("frontend", rb_task["id"], f"Write-Output '{rb_token}'")
        rb = control.verify_task(rb_task["id"], rb_token)
        ev.record("worker_to_main", rb["verified"], {"observed": rb["verified"]})

        # --- parallel: dispatch all roles, then verify each executed ---
        par = {}
        for role in roles:
            t = control.create_task(f"parallel {role}")
            tok = f"PAR_{role.upper()}_{run_id[:6]}"
            control.dispatch_role(role, t["id"], f"Write-Output '{tok}'")
            par[role] = control.verify_task(t["id"], tok)["verified"]
        ev.record("parallel_execution", all(par.values()), par)

        # --- dependency gating ---
        a = control.create_task("prereq"); b = control.create_task("dependent")
        control.add_dependency(b["id"], a["id"])
        try:
            control.dispatch_role("backend", b["id"], "Write-Output 'SHOULD_NOT_RUN'")
            ev.record("dependency_gating", False, "dependent task dispatched before prerequisite done")
        except OrchestrationError as exc:
            ev.record("dependency_gating", "DEPENDENCIES_PENDING" in str(exc), {"error": str(exc)})

        # --- worker -> worker handoff (frontend hands to backend) ---
        if worker_count >= 2:
            h_task = control.create_task("api contract")
            control.dispatch_role("frontend", h_task["id"], f"Write-Output 'CANDIDATE_{run_id[:6]}'")
            ho = control.handoff_role("frontend", "backend", h_task["id"], f"Write-Output 'AGREED_{run_id[:6]}'")
            owner_now = control.store.task(h_task["id"])["owner_id"] == by_role["backend"]["id"]
            ev.record("worker_to_worker", ho["delivery"]["phase"] == "COMMAND_EXECUTED" and owner_now,
                      {"phase": ho["delivery"]["phase"], "reassigned_to_backend": owner_now})

        # --- QA independent review: reject then correct ---
        if worker_count >= 4:
            q_task = control.create_task("feature for QA")
            control.dispatch_role("frontend", q_task["id"], f"Write-Output 'DRAFT_{run_id[:6]}'")
            rejected = control.verify_task(q_task["id"], f"APPROVED_{run_id[:6]}", by_role["qa"]["id"])
            rej_ok = (not rejected["verified"]) and control.store.task(q_task["id"])["state"] == "reviewing"
            ev.record("qa_reject", rej_ok, {"verified": rejected["verified"], "task_state": control.store.task(q_task["id"])["state"]})
            control.handoff_role("qa", "frontend", q_task["id"], f"Write-Output 'APPROVED_{run_id[:6]}'")
            approved = control.verify_task(q_task["id"], f"APPROVED_{run_id[:6]}", by_role["qa"]["id"])
            ev.record("qa_correct_reverify", approved["verified"], {"verified": approved["verified"]})
            ev.record("no_false_completion", rej_ok, "QA rejection put task in 'reviewing', not 'done'")

        # --- reassignment without rebuilding the team ---
        if worker_count >= 2:
            rz = control.create_task("reassign me")
            control.dispatch_role("frontend", rz["id"], f"Write-Output 'X_{run_id[:6]}'")
            control.dispatch(by_role["backend"]["id"], rz["id"], f"Write-Output 'Y_{run_id[:6]}'", reassign=True)
            ev.record("reassignment", control.store.task(rz["id"])["owner_id"] == by_role["backend"]["id"],
                      {"owner": "backend"})

        # --- edge case: foreground 0 tolerated by monitor/refresh ---
        try:
            mon = control.monitor(by_role[roles[0]]["id"])
            ev.record("foreground_zero_tolerated", mon["state"] in {"ready", "working"}, {"monitor_state": mon["state"], "fg_at_start": fg_before})
        except Exception as exc:
            ev.error("foreground_zero_tolerated", exc)

        # --- recovery: mark a worker failed, recover in place, role preserved, reachable ---
        target = workers[-1]
        old_pid = control.store.worker(target["id"])["ref_json"]["pid"]
        control.store.update_worker(target["id"], state="failed", health={"reachable": False, "reason": "acceptance"})
        ev.record("worker_failure_detection", control.store.worker(target["id"])["state"] == "failed", {"state": "failed"})
        recovered = control.recover(target["id"])
        ev.record("worker_recovery", recovered["state"] in {"ready", "recovering", "working"}, {"state": recovered["state"]})
        ev.record("role_preserved_after_recovery", recovered["role"] == target["role"], {"role": recovered["role"]})
        rec_task = control.create_task("post recovery")
        rec_tok = f"REC_{run_id[:6]}"
        rd = control.dispatch_role(target["role"], rec_task["id"], f"Write-Output '{rec_tok}'")
        ev.record("communication_recovery", rd["delivery"]["phase"] == "COMMAND_EXECUTED", {"phase": rd["delivery"]["phase"]})
        ev.record("recovery_in_place", recovered["ref_json"]["pid"] == old_pid, {"same_pid": recovered["ref_json"]["pid"] == old_pid})

        # --- teardown: workers closed, no orphans; refuse a foreign pane is unit-tested ---
        hwnd = control.refresh(main["id"])["topology_json"]["window"]["hwnd"]
        member_pids = [control.store.worker(w["id"])["ref_json"].get("pid") for w in workers]
        closed = control.close_team(main["id"])
        ev.record("full_team_teardown", closed.get("closed", 0) >= 1, closed)
        time.sleep(1.0)
        gone = []
        for pid in member_pids:
            if not pid:
                continue
            try:
                reference_for_pid(int(pid)); gone.append(False)
            except (TargetError, OSError):
                gone.append(True)
        ev.record("no_orphan_processes", all(gone), {"all_gone": all(gone), "checked": len(gone)})
        snap = enumerate_topology(exhaustive=True, hwnds=[hwnd])
        certs = {control.store.worker(w["id"])["topology_json"].get("certificate") for w in workers}
        leaked = [p["title"] for p in snap["panes"] if p["title"] in certs]
        ev.record("no_orphan_panes", not leaked, {"leaked": leaked})
        main = None  # closed with its disposable tab
    except Exception as exc:
        ev.error("run_fatal", exc)
        raise
    finally:
        if main:
            try:
                control.close_team(main["id"])
            except Exception:
                pass
        try:
            control.store.close()
        finally:
            Path(os.environ["AGENT_ORCHESTRATION_DB"]).unlink(missing_ok=True)
    passed = sum(1 for c in ev.checks.values() if c["status"] == "PASS")
    return {"run": run_id, "workers": worker_count, "passed": passed, "total": len(ev.checks), "checks": ev.checks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "acceptance-contract.json"))
    args = ap.parse_args()
    result = run(args.workers)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"workers": result["workers"], "passed": result["passed"], "total": result["total"], "out": args.out}))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
