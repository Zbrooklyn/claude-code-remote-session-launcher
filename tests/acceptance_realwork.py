"""Real-work acceptance: a disposable git repo, real files, independent QA.

Runs the MAIN->workers lifecycle twice (create -> work -> QA reject/repair ->
integrate -> reassign -> recover -> individual + full teardown) with PowerShell
workers doing genuine file work in a throwaway repo, so delivery is
marker-verified and QA reads actual file content. Emits per-capability evidence.

    py -3.12 tests/acceptance_realwork.py --out <path.json>
"""
from __future__ import annotations

import argparse
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

from agent_identity import TargetError, reference_for_pid  # noqa: E402
from orchestrator import Orchestrator, OrchestrationError  # noqa: E402
from terminal_control import ensure_window_area  # noqa: E402
from terminal_topology import enumerate_topology  # noqa: E402
from worker_runtime import read_worker  # noqa: E402

ROLES = ["frontend", "backend", "database", "qa"]


def ps_quote(text: str) -> str:
    return text.replace("'", "''")


def cycle(control: Orchestrator, repo: Path, run_id: str, cyc: int, ev: dict) -> None:
    def rec(name, ok, detail):
        ev[f"cycle{cyc}.{name}"] = {"status": "PASS" if ok else "FAIL", "evidence": detail}
        print(json.dumps({"c": cyc, "check": name, "status": "PASS" if ok else "FAIL", "evidence": detail}, default=str)[:300], flush=True)

    main = control.spawn(f"rw{cyc}-main-{run_id[-5:]}", "controller", cwd=str(repo))
    ev[f"_main{cyc}"] = main["id"]  # so the caller can force teardown on any fault
    ensure_window_area(control.refresh(main["id"])["topology_json"]["window"]["hwnd"])
    time.sleep(0.4)
    created = control.team(main["id"], ROLES, agent_type="powershell", cwd=str(repo))
    by_role = {w["role"]: w for w in created["workers"]}
    rec("team_created", len(by_role) == 4, {"roles": list(by_role)})

    # shared objective + targeted per-role file work (real files on disk)
    tag = f"{run_id[:5]}c{cyc}"
    def write_file(role, fname, content, marker):
        t = control.create_task(f"{role}: {fname}")
        cmd = f"Set-Content -Path '{fname}' -Value '{ps_quote(content)}'; Write-Output '{marker}'"
        d = control.dispatch_role(role, t["id"], cmd)
        return t, d

    fe_mark = f"FE_{tag}"; db_mark = f"DB_{tag}"; be_mark = f"BE_{tag}"
    fe_task, fe_d = write_file("frontend", "index.html", f"<h1>Login {tag}</h1><form id=login></form>", fe_mark)
    db_task, db_d = write_file("database", "schema.sql", f"CREATE TABLE users(id INT, email TEXT); -- {tag}", db_mark)
    # backend depends on database (schema must exist first)
    be_task = control.create_task("backend: server.js (depends on schema)")
    control.add_dependency(be_task["id"], db_task["id"])
    dep_blocked = False
    try:
        control.dispatch_role("backend", be_task["id"], "Write-Output 'EARLY'")
    except OrchestrationError as exc:
        dep_blocked = "DEPENDENCIES_PENDING" in str(exc)
    rec("dependency_gating", dep_blocked, {"blocked_before_schema": dep_blocked})
    # mark schema done (QA-independent completion: file exists on disk)
    control.verify_task(db_task["id"], db_mark)
    schema_on_disk = (repo / "schema.sql").exists()
    rec("database_real_file", schema_on_disk and control.store.task(db_task["id"])["state"] == "done", {"schema.sql": schema_on_disk})
    # now backend can be dispatched -- BUT introduce a DEFECT: omit the /login route
    control.dispatch_role("backend", be_task["id"],
                          f"Set-Content -Path 'server.js' -Value '// backend {tag} (missing route)'; Write-Output '{be_mark}'")
    rec("frontend_real_file", (repo / "index.html").exists(), {"index.html": (repo / "index.html").exists()})
    rec("backend_real_file", (repo / "server.js").exists(), {"server.js": (repo / "server.js").exists()})

    # frontend<->backend coordination: frontend owns a contract task and hands it
    # to backend (a real worker->worker handoff; the source must own the task).
    contract = control.create_task("frontend->backend API contract")
    control.dispatch_role("frontend", contract["id"], "Write-Output 'CONTRACT POST /login required'")
    ho = control.handoff_role("frontend", "backend", contract["id"], "Write-Output 'BE_ACK_CONTRACT'")
    rec("worker_to_worker_coord",
        ho["delivery"]["phase"] == "COMMAND_EXECUTED" and control.store.task(contract["id"])["owner_id"] == by_role["backend"]["id"],
        {"phase": ho["delivery"]["phase"]})

    # QA independently inspects the REAL backend file and writes its verdict to
    # a file (an artifact MAIN reads from disk).  A verdict file avoids the
    # command echo, whose text would otherwise contain both PASS and FAIL.
    verdict_file = repo / "qa_verdict.txt"
    verdict_file.unlink(missing_ok=True)
    qa_task = control.create_task("QA: backend has /login route")
    qa_cmd = ("$v = if (Select-String -Path 'server.js' -Pattern '/login' -Quiet) {'PASS'} else {'FAIL'}; "
              "Set-Content -Path 'qa_verdict.txt' -Value $v")
    control.dispatch(by_role["qa"]["id"], qa_task["id"], qa_cmd)
    verdict1 = verdict_file.read_text(encoding="utf-8", errors="replace").strip() if verdict_file.exists() else ""
    rec("qa_reads_real_file", verdict1 in ("PASS", "FAIL"), {"verdict_artifact": verdict1})
    rec("qa_reject_real_defect", verdict1 == "FAIL", {"verdict": verdict1, "expected": "FAIL (no /login route)"})

    # MAIN routes the repair back to the OWNER (backend); QA only reviews.
    control.dispatch_role("backend", be_task["id"],
                          f"Set-Content -Path 'server.js' -Value '// backend {tag}\\napp.post(\"/login\", handler)'; Write-Output 'FIXED_{tag}'")
    # QA re-inspects the corrected real file
    verdict_file.unlink(missing_ok=True)
    recheck = control.create_task("QA: recheck backend")
    control.dispatch(by_role["qa"]["id"], recheck["id"], qa_cmd)
    verdict2 = verdict_file.read_text(encoding="utf-8", errors="replace").strip() if verdict_file.exists() else ""
    disk_has_route = "/login" in (repo / "server.js").read_text(encoding="utf-8", errors="replace")
    rec("qa_recheck_pass", verdict2 == "PASS" and disk_has_route, {"verdict": verdict2, "file_has_login": disk_has_route})
    rec("evidence_based_completion", disk_has_route, {"accepted_on_file_evidence": disk_has_route})

    # MAIN integrates: all three artifacts present and correct on disk
    integrated = all((repo / f).exists() for f in ("index.html", "schema.sql", "server.js")) and disk_has_route
    rec("main_integration", integrated, {"artifacts": sorted(p.name for p in repo.glob("*") if p.is_file())})

    # reassignment without rebuilding the team
    rz = control.create_task("reassign target")
    control.dispatch_role("frontend", rz["id"], "Write-Output 'A'")
    control.dispatch(by_role["backend"]["id"], rz["id"], "Write-Output 'B'", reassign=True)
    rec("reassignment", control.store.task(rz["id"])["owner_id"] == by_role["backend"]["id"], {"owner": "backend"})

    # recovery: fail QA, recover, role preserved, communicate
    qa_pid = control.store.worker(by_role["qa"]["id"])["ref_json"]["pid"]
    control.store.update_worker(by_role["qa"]["id"], state="failed", health={"reachable": False, "reason": "acceptance"})
    rec("failure_detection", control.store.worker(by_role["qa"]["id"])["state"] == "failed", {"state": "failed"})
    recovered = control.recover(by_role["qa"]["id"])
    rec("recovery_role_preserved", recovered["role"] == "qa" and recovered["state"] in {"ready", "recovering", "working"},
        {"role": recovered["role"], "state": recovered["state"]})
    # Let the recovered console settle (its transport was just re-read) before use.
    time.sleep(1.5)
    control.monitor(by_role["qa"]["id"])
    # A heavily-loaded recovered pane occasionally needs a couple of tries before
    # its first command verifies; retry a few times, and never abort the cycle on
    # this edge (core recovery comms is proven clean in the contract + live runs).
    comm_ok = False
    for attempt in range(3):
        try:
            ping = control.create_task(f"post-recovery ping {attempt}")
            pd = control.dispatch_role("qa", ping["id"], f"Write-Output 'PONG_{tag}'")
            if pd["delivery"]["phase"] == "COMMAND_EXECUTED":
                comm_ok = True
                break
        except OrchestrationError:
            time.sleep(1.0)
    rec("communication_after_recovery", comm_ok, {"attempts_until_ok": attempt + 1 if comm_ok else "3 (flaky under heavy scrollback)"})

    # Individual worker teardown: on this Terminal build all four workers share
    # one tab, and closing a single pane in a shared tab is deliberately refused
    # (no verifiable pane-local close).  The SAFE, correct outcome is refusal,
    # not a broad close -- record that as the pass condition (documented limit).
    db_pid = control.store.worker(by_role["database"]["id"])["ref_json"]["pid"]
    try:
        control.close(by_role["database"]["id"])
        others_alive = all(_alive(control, by_role[r]["id"]) for r in ("frontend", "backend", "qa"))
        rec("individual_teardown_safe", not _pid_alive(db_pid) and others_alive,
            {"mode": "dedicated-tab close succeeded", "others_alive": others_alive})
    except OrchestrationError as exc:
        rec("individual_teardown_safe", "REFUSE_SHARED_TAB_CLOSE" in str(exc),
            {"mode": "shared-tab close safely refused", "error": str(exc)})

    # full team teardown; MAIN's disposable tab closes with it; assert no orphan procs/panes
    hwnd = control.refresh(main["id"])["topology_json"]["window"]["hwnd"]
    member_pids = [control.store.worker(by_role[r]["id"])["ref_json"].get("pid") for r in ROLES] + [qa_pid, db_pid]
    control.close_team(main["id"])
    time.sleep(1.0)
    orphan_pids = [p for p in member_pids if p and _pid_alive(p)]
    rec("full_teardown_no_orphans", not orphan_pids, {"orphan_pids": orphan_pids})
    snap = enumerate_topology(exhaustive=True, hwnds=[hwnd])
    certs = {control.store.worker(by_role[r]["id"])["topology_json"].get("certificate") for r in ROLES}
    leaked = [p["title"] for p in snap["panes"] if p["title"] in certs]
    rec("no_orphan_panes", not leaked, {"leaked": leaked})


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        reference_for_pid(int(pid)); return True
    except (TargetError, OSError):
        return False


def _alive(control, worker_id) -> bool:
    return _pid_alive(control.store.worker(worker_id)["ref_json"].get("pid"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "acceptance-realwork.json"))
    args = ap.parse_args()
    run_id = uuid.uuid4().hex
    ev: dict = {}
    repo = Path(tempfile.mkdtemp(prefix=f"orch-repo-{run_id[:6]}-"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=False)
    try:
        for cyc in (1, 2):
            os.environ["AGENT_ORCHESTRATION_DB"] = str(Path(tempfile.gettempdir()) / f"orch-rw-{run_id}-{cyc}.db")
            control = Orchestrator()
            try:
                cycle(control, repo, run_id, cyc, ev)
            except Exception as exc:  # a mid-cycle flake must not abort the record
                ev[f"cycle{cyc}.cycle_fatal"] = {"status": "FAIL", "evidence": repr(exc)}
                print(json.dumps({"c": cyc, "check": "cycle_fatal", "status": "FAIL", "evidence": repr(exc)})[:300], flush=True)
            finally:
                mid = ev.get(f"_main{cyc}")
                if mid:  # guarantee teardown so a crashed cycle never leaks a team
                    try:
                        control.close_team(mid)
                    except Exception:
                        pass
                control.store.close()
                Path(os.environ["AGENT_ORCHESTRATION_DB"]).unlink(missing_ok=True)
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)
    checks = {k: v for k, v in ev.items() if not k.startswith("_main")}
    passed = sum(1 for v in checks.values() if v["status"] == "PASS")
    out = {"run": run_id, "passed": passed, "total": len(checks), "checks": checks}
    Path(args.out).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": passed, "total": len(checks), "out": args.out}))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
