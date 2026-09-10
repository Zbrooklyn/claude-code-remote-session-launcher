#!/usr/bin/env python3
"""Bridge-owned disposable worker lifecycle and exact topology binding."""
from __future__ import annotations

import json
import secrets
import subprocess
import time
from pathlib import Path

from agent_identity import reference_for_pid
from agentctl import read as read_console, send as send_console
from orchestration_store import Store
from terminal_topology import TopologyError, bind_certificate, enumerate_topology
from terminal_control import read_scrollback, split_relative


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


def _topology_for_binding(certificate: str, ref: dict, screen: str, window_name: str,
                          hwnds: list[int] | None = None) -> dict:
    topology = enumerate_topology(exhaustive=bool(hwnds), hwnds=hwnds)
    pane = bind_certificate(topology, certificate, ref, screen)
    tab = next(tab for tab in topology["tabs"] if tab["bridge_id"] == pane["tab_id"])
    window = next(win for win in topology["windows"] if win["bridge_id"] == tab["window_id"])
    return {"window": window, "tab": tab, "pane": pane, "certificate": certificate, "window_name": window_name}


def _launch_worker(store: Store, worker: dict, engine: str, parent: dict | None = None) -> dict:
    certificate = f"ORCH_{worker['id'][-12:]}_{secrets.token_hex(12)}"
    # Windows Terminal owns the pane title through --title. Do not put a
    # semicolon in this command: wt interprets it as a commandline separator.
    command = f"Write-Output '{certificate}'"
    window_name = f"orch-{worker['id']}" if parent is None else parent["topology_json"]["window_name"]
    if parent is None:
        subprocess.run(["wt.exe", "-w", window_name, "new-tab", "-d", str(Path.cwd()), "--title", certificate, engine, "-NoExit", "-Command", command],
                       check=False, timeout=15)
    else:
        split_relative(parent["topology_json"], engine, certificate, command)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        pid = _query_worker_process(engine, certificate)
        if pid:
            ref = reference_for_pid(pid).to_dict()
            screen = read_console(str(pid))["screen"]
            try:
                scoped_hwnd = [parent["topology_json"]["window"]["hwnd"]] if parent else None
                topology = _topology_for_binding(certificate, ref, screen, window_name, scoped_hwnd)
            except TopologyError:
                time.sleep(0.1)
                continue
            return store.update_worker(worker["id"], state="ready", ref=ref,
                                       topology=topology,
                                       health={"reachable": True, "bound_at": time.time()})
        time.sleep(0.1)
    store.update_worker(worker["id"], state="failed", health={"reachable": False, "reason": "topology binding timeout"})
    raise WorkerRuntimeError(f"Could not bind worker {name} to a Windows Terminal pane.")


def spawn_worker(store: Store, name: str, role: str, engine: str = "powershell.exe",
                 parent_worker_id: str | None = None, agent_type: str = "powershell") -> dict:
    worker = store.create_worker(name, role, agent_type)
    parent = store.worker(parent_worker_id) if parent_worker_id else None
    if parent and not parent.get("topology_json"):
        raise WorkerRuntimeError("PARENT_TOPOLOGY_UNBOUND")
    launched = _launch_worker(store, worker, engine, parent)
    if agent_type.lower() in {"claude", "codex"}:
        # The certified PowerShell remains the control endpoint while the
        # interactive agent runs inside its console.  Agent input intentionally
        # has no shell marker: completion must come from an explicit predicate.
        send_worker_input(store, launched["id"], agent_type.lower())
        return store.worker(launched["id"])
    return launched


def refresh_worker_topology(store: Store, worker_id: str) -> dict:
    """Re-resolve RuntimeIds after a terminal topology change without title-only matching."""
    worker = store.worker(worker_id)
    ref = worker.get("ref_json") or {}
    topology = worker.get("topology_json") or {}
    certificate = topology.get("certificate")
    try:
        current = reference_for_pid(int(ref["pid"])).to_dict()
        if current["process_start_time"] != ref.get("process_start_time"):
            raise WorkerRuntimeError("STALE_TARGET")
        screen = read_console(str(current["pid"]), current["process_start_time"])["screen"]
        hwnd = topology.get("window", {}).get("hwnd")
        refreshed = _topology_for_binding(certificate, current, screen, topology["window_name"], [hwnd] if hwnd else None)
    except (KeyError, TopologyError, WorkerRuntimeError, OSError) as exc:
        if worker["state"] not in {"done", "failed", "disconnected"}:
            store.update_worker(worker_id, state="disconnected",
                                health={"reachable": False, "reason": str(exc)})
        raise WorkerRuntimeError(f"WORKER_DISCONNECTED: {exc}") from exc
    return store.update_worker(worker_id, ref=current, topology=refreshed,
                               health={"reachable": True, "refreshed_at": time.time()})


def restart_worker(store: Store, worker_id: str, engine: str = "powershell.exe") -> dict:
    """Replace a disconnected/failed worker while preserving its logical ID."""
    worker = store.worker(worker_id)
    if worker["state"] not in {"failed", "disconnected"}:
        raise WorkerRuntimeError("RESTART_REQUIRES_FAILED_OR_DISCONNECTED_WORKER")
    store.record_retry(worker_id, "controlled replacement")
    recovering = store.update_worker(worker_id, state="recovering", ref={}, topology={},
                                     health={"reachable": False, "reason": "replacement starting"})
    return _launch_worker(store, recovering, engine)


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


def send_worker_input(store: Store, worker_id: str, message: str) -> dict:
    """Send raw interactive agent input; never claim command/task completion."""
    worker = store.worker(worker_id)
    if worker["state"] in {"failed", "done", "disconnected"}:
        raise WorkerRuntimeError(f"Worker {worker_id} is not writable in state {worker['state']}.")
    ref = worker["ref_json"]
    if not ref:
        raise WorkerRuntimeError(f"Worker {worker_id} has no live AgentRef.")
    result = send_console(str(ref["pid"]), message, True, None, 5.0, ref["process_start_time"])
    store.update_worker(worker_id, state="working",
                        health={"reachable": True, "last_phase": result["phase"], "delivery": "input"})
    return result


def read_worker(store: Store, worker_id: str) -> dict:
    worker = store.worker(worker_id)
    ref = worker["ref_json"]
    if not ref:
        raise WorkerRuntimeError(f"Worker {worker_id} has no live AgentRef.")
    return read_console(str(ref["pid"]), ref["process_start_time"])


def read_worker_scrollback(store: Store, worker_id: str) -> dict:
    """Return attributed Terminal scrollback after revalidating PID and pane."""
    refreshed = refresh_worker_topology(store, worker_id)
    return {"worker_id": worker_id, "scrollback": read_scrollback(refreshed["topology_json"])}


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
