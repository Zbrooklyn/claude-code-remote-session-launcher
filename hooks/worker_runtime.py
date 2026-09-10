#!/usr/bin/env python3
"""Bridge-owned disposable worker lifecycle and exact topology binding."""
from __future__ import annotations

import json
import secrets
import subprocess
import time

from agent_identity import reference_for_pid
from agentctl import read as read_console, send as send_console
from orchestration_store import Store
from terminal_topology import TopologyError, bind_certificate, enumerate_topology


class WorkerRuntimeError(RuntimeError):
    pass


def _query_worker_process(engine: str, certificate: str) -> int | None:
    name = engine.rsplit("\\", 1)[-1]
    script = (
        "$p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq '%s' -and $_.CommandLine -like '*%s*' -and $_.CommandLine -match '(?i)(powershell|pwsh)\\.exe\\s+-NoExit' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId; $p" % (name, certificate)
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=15, check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def spawn_worker(store: Store, name: str, role: str, engine: str = "powershell.exe") -> dict:
    worker = store.create_worker(name, role, "powershell")
    certificate = f"ORCH_{worker['id'][-12:]}_{secrets.token_hex(12)}"
    # Windows Terminal owns the pane title through --title. Do not put a
    # semicolon in this command: wt interprets it as a commandline separator.
    command = f"Write-Output '{certificate}'"
    subprocess.run(["wt.exe", "-w", "new", "new-tab", "--title", certificate, engine, "-NoExit", "-Command", command],
                   check=False, timeout=15)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        pid = _query_worker_process(engine, certificate)
        if pid:
            ref = reference_for_pid(pid).to_dict()
            screen = read_console(str(pid))["screen"]
            try:
                topology = enumerate_topology()
                pane = bind_certificate(topology, certificate, ref, screen)
            except TopologyError:
                time.sleep(0.1)
                continue
            tab = next(tab for tab in topology["tabs"] if tab["bridge_id"] == pane["tab_id"])
            window = next(win for win in topology["windows"] if win["bridge_id"] == tab["window_id"])
            return store.update_worker(worker["id"], state="ready", ref=ref,
                                       topology={"window": window, "tab": tab, "pane": pane, "certificate": certificate},
                                       health={"reachable": True, "bound_at": time.time()})
        time.sleep(0.1)
    store.update_worker(worker["id"], state="failed", health={"reachable": False, "reason": "topology binding timeout"})
    raise WorkerRuntimeError(f"Could not bind worker {name} to a Windows Terminal pane.")


def send_worker(store: Store, worker_id: str, command: str, marker: str | None = None) -> dict:
    worker = store.worker(worker_id)
    if worker["state"] in {"failed", "done", "disconnected"}:
        raise WorkerRuntimeError(f"Worker {worker_id} is not writable in state {worker['state']}.")
    ref = worker["ref_json"]
    if not ref:
        raise WorkerRuntimeError(f"Worker {worker_id} has no live AgentRef.")
    result = send_console(str(ref["pid"]), command, True, marker, 5.0, ref["process_start_time"])
    store.update_worker(worker_id, state="working", health={"reachable": True, "last_phase": result["phase"]})
    return result


def read_worker(store: Store, worker_id: str) -> dict:
    worker = store.worker(worker_id)
    ref = worker["ref_json"]
    if not ref:
        raise WorkerRuntimeError(f"Worker {worker_id} has no live AgentRef.")
    return read_console(str(ref["pid"]), ref["process_start_time"])


def terminate_worker(store: Store, worker_id: str) -> None:
    """Terminate only a bridge-owned worker whose certificate is still present."""
    worker = store.worker(worker_id)
    ref = worker["ref_json"] or {}
    certificate = (worker["topology_json"] or {}).get("certificate", "")
    if not certificate or certificate not in (ref.get("command_line") or ""):
        raise WorkerRuntimeError("REFUSE_UNOWNED_WORKER: no bridge certificate in target command line.")
    current = reference_for_pid(int(ref["pid"])).to_dict()
    if current["process_start_time"] != ref["process_start_time"]:
        raise WorkerRuntimeError("STALE_TARGET")
    subprocess.run(["taskkill.exe", "/PID", str(ref["pid"]), "/F"], capture_output=True, text=True, timeout=15, check=False)
    store.update_worker(worker_id, state="failed", health={"reachable": False, "reason": "terminated by orchestrator"})
