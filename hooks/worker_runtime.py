#!/usr/bin/env python3
"""Bridge-owned disposable worker lifecycle and exact topology binding."""
from __future__ import annotations

import base64
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from agent_identity import TargetError, reference_for_pid
from agentctl import read as read_console, send as send_console
from native_console import attached_console, console_title, set_console_title
from orchestration_store import Store
from terminal_topology import TopologyError, bind_certificate, enumerate_topology
from terminal_control import close_pane_and_verify, read_scrollback, split_relative


class WorkerRuntimeError(RuntimeError):
    pass


def _read_pid_rendezvous(path: Path) -> int | None:
    """Read only a complete, positive PID written by this worker's startup command."""
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def _startup_command(certificate: str, rendezvous: Path) -> str:
    """Emit the launch certificate, publish PID, then restore the pane title."""
    rendezvous_literal = str(rendezvous).replace("'", "''")
    script = (
        f"Write-Output '{certificate}'; "
        f"[System.IO.File]::WriteAllText('{rendezvous_literal}', [string]$PID); "
        f"$Host.UI.RawUI.WindowTitle='{certificate}'"
    )
    payload = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # Windows Terminal treats literal semicolons as command separators even
    # inside an argv element. Keep the payload opaque and retain the visible
    # certificate in a PowerShell comment for PID-safe teardown validation.
    return f"iex ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{payload}'))) # {certificate}"


def _terminate_unbound_launch(ref: dict, certificate: str) -> None:
    """Best-effort cleanup after a failed bridge bind, never by PID alone."""
    if certificate not in (ref.get("command_line") or ""):
        return
    try:
        current = reference_for_pid(int(ref["pid"])).to_dict()
    except (TargetError, KeyError, ValueError):
        return
    if current.get("process_start_time") != ref.get("process_start_time"):
        return
    if certificate not in (current.get("command_line") or ""):
        return
    subprocess.run(["taskkill.exe", "/PID", str(ref["pid"]), "/F"], capture_output=True, text=True, timeout=15, check=False)


def _topology_for_binding(certificate: str, ref: dict, screen: str, window_name: str,
                          hwnds: list[int] | None = None) -> dict:
    # A relative split is made after focusing the certified parent pane, so
    # its tab is already active.  Avoid selecting inactive tabs during this
    # timing-sensitive bind; later lifecycle operations may opt into the
    # explicitly scoped exhaustive scan when they need it.
    topology = enumerate_topology(exhaustive=False, hwnds=hwnds)
    pane = bind_certificate(topology, certificate, ref, screen)
    tab = next(tab for tab in topology["tabs"] if tab["bridge_id"] == pane["tab_id"])
    window = next(win for win in topology["windows"] if win["bridge_id"] == tab["window_id"])
    return {"window": window, "tab": tab, "pane": pane, "certificate": certificate, "window_name": window_name}


def _topology_for_refresh(certificate: str, ref: dict, window_name: str,
                          hwnds: list[int] | None = None) -> dict:
    """Refresh a previously two-channel-bound pane when Terminal text redraws.

    The durable proof is the original certificate binding plus the same live
    PID/start-time/command line.  A unique certificate pane in the original
    owned window rebinds only its volatile UIA runtime, never a title alone.
    """
    topology = enumerate_topology(exhaustive=False, hwnds=hwnds)
    panes = [pane for pane in topology["panes"] if pane.get("title") == certificate]
    if len(panes) != 1:
        raise TopologyError("REFRESH_CERTIFICATE_PANE_UNPROVEN")
    pane = panes[0]
    tab = next(tab for tab in topology["tabs"] if tab["bridge_id"] == pane["tab_id"])
    window = next(win for win in topology["windows"] if win["bridge_id"] == tab["window_id"])
    return {"window": window, "tab": tab, "pane": pane, "certificate": certificate, "window_name": window_name}


def _launch_worker(store: Store, worker: dict, engine: str, parent: dict | None = None,
                   cwd: str | None = None, direction: str = "right", size: float | None = None) -> dict:
    certificate = f"ORCH_{worker['id'][-12:]}_{secrets.token_hex(12)}"
    rendezvous = Path(tempfile.gettempdir()) / f"orch-worker-{worker['id']}-{secrets.token_hex(8)}.pid"
    # Windows Terminal owns the pane title through --title. Do not put a
    # semicolon in this command: wt interprets it as a commandline separator.
    command = _startup_command(certificate, rendezvous)
    window_name = f"orch-{worker['id']}" if parent is None else parent["topology_json"]["window_name"]
    if parent is None:
        subprocess.run(["wt.exe", "-w", window_name, "new-tab", "-d", cwd or str(Path.cwd()), "--title", certificate, engine, "-NoExit", "-Command", command],
                       check=False, timeout=15)
    else:
        split_relative(parent["topology_json"], engine, certificate, command, direction, size, cwd)
    bound = False
    last_ref: dict | None = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            pid = _read_pid_rendezvous(rendezvous)
            if pid:
                try:
                    ref = reference_for_pid(pid).to_dict()
                except TargetError:
                    time.sleep(0.1)
                    continue
                if certificate not in (ref.get("command_line") or ""):
                    time.sleep(0.1)
                    continue
                last_ref = ref
                screen = read_console(str(pid))["screen"]
                try:
                    scoped_hwnd = [parent["topology_json"]["window"]["hwnd"]] if parent else None
                    topology = _topology_for_binding(certificate, ref, screen, window_name, scoped_hwnd)
                except TopologyError:
                    time.sleep(0.1)
                    continue
                bound = True
                return store.update_worker(worker["id"], state="ready", ref=ref,
                                           topology=topology,
                                           health={"reachable": True, "bound_at": time.time()})
            time.sleep(0.1)
        store.update_worker(worker["id"], state="failed", health={"reachable": False, "reason": "topology binding timeout"})
        raise WorkerRuntimeError(f"Could not bind worker {worker['name']} to a Windows Terminal pane.")
    finally:
        rendezvous.unlink(missing_ok=True)
        if not bound and last_ref:
            _terminate_unbound_launch(last_ref, certificate)


def spawn_worker(store: Store, name: str, role: str, engine: str = "powershell.exe",
                 parent_worker_id: str | None = None, agent_type: str = "powershell",
                 cwd: str | None = None, direction: str = "right", size: float | None = None,
                 agent_command: str | None = None) -> dict:
    worker = store.create_worker(name, role, agent_type, parent_id=parent_worker_id)
    parent = store.worker(parent_worker_id) if parent_worker_id else None
    if parent and not parent.get("topology_json"):
        raise WorkerRuntimeError("PARENT_TOPOLOGY_UNBOUND")
    launched = _launch_worker(store, worker, engine, parent, cwd, direction, size)
    if agent_type.lower() in {"claude", "codex"}:
        # The certified PowerShell remains the control endpoint while the
        # interactive agent runs inside its console.  Agent input intentionally
        # has no shell marker: completion must come from an explicit predicate.
        send_worker_input(store, launched["id"], agent_command or agent_type.lower())
        return store.worker(launched["id"])
    return launched


_ADOPT_TIMEOUT = 8.0


def adopt_main(store: Store, name: str, pid: int, agent_type: str = "claude") -> dict:
    """Adopt an already-running pane host as the certified MAIN controller.

    A spawned worker proves its pane with a certificate in its command line and
    a ``--title`` pane.  An existing process has neither, so adoption uses a
    different two-channel proof: the certificate is written as the title of
    the exact PID's console (ConPTY forwards it to Terminal), and exactly one
    Terminal tab must carry that title while holding exactly one pane.  The
    user's title is restored afterwards.  The process itself stays untouched.
    """
    ref = reference_for_pid(int(pid)).to_dict()
    worker = store.create_worker(name, "controller", agent_type)
    certificate = f"ORCH_MAIN_{worker['id'][-12:]}_{secrets.token_hex(12)}"
    previous_title: str | None = None
    try:
        with attached_console(int(pid)):
            previous_title = console_title()
            set_console_title(certificate)
            if console_title() != certificate:
                raise WorkerRuntimeError("ADOPT_UNPROVEN: console title did not take.")
        deadline = time.monotonic() + _ADOPT_TIMEOUT
        last = "ADOPT_UNPROVEN: certificate tab not observed."
        while time.monotonic() < deadline:
            topology = enumerate_topology(exhaustive=False, hwnds=None)
            tabs = [tab for tab in topology["tabs"] if tab["title"] == certificate]
            if len(tabs) == 1:
                panes = [pane for pane in topology["panes"] if pane["tab_id"] == tabs[0]["bridge_id"]]
                if len(panes) != 1:
                    last = f"ADOPT_UNPROVEN: certificate tab holds {len(panes)} panes, expected 1."
                    break
                window = next(win for win in topology["windows"] if win["bridge_id"] == tabs[0]["window_id"])
                bound = {"window": window, "tab": tabs[0], "pane": panes[0], "certificate": certificate,
                         "window_name": "last", "adopted": True, "pane_title": panes[0]["title"]}
                return store.update_worker(worker["id"], state="ready", ref=ref, topology=bound,
                                           health={"reachable": True, "bound_at": time.time(), "adopted": True})
            if len(tabs) > 1:
                last = f"ADOPT_UNPROVEN: certificate resolves to {len(tabs)} tabs."
                break
            # The hosted agent may repaint its own title; reassert and retry.
            with attached_console(int(pid)):
                set_console_title(certificate)
            time.sleep(0.15)
        store.update_worker(worker["id"], state="failed", health={"reachable": False, "reason": last})
        raise WorkerRuntimeError(last)
    finally:
        if previous_title is not None:
            try:
                with attached_console(int(pid)):
                    set_console_title(previous_title)
            except Exception:
                pass


def _topology_for_adopted_refresh(store: Store, worker: dict, current: dict) -> dict:
    """Rebind an adopted MAIN pane by elimination inside its own tab.

    The process proof is PID/start time.  The pane proof is: the owned tab (by
    stored tab runtime, else the active tab in the owned window) contains every
    live child worker's certificate pane and exactly one pane that is not a
    bridge certificate pane, whose title matches the one bound at adoption.
    """
    topology = worker["topology_json"]
    hwnd = topology["window"]["hwnd"]
    snapshot = enumerate_topology(exhaustive=False, hwnds=[hwnd])
    tabs = [tab for tab in snapshot["tabs"] if tab["runtime_id"] == topology["tab"]["runtime_id"]]
    if len(tabs) != 1:
        tabs = [tab for tab in snapshot["tabs"] if tab["active"]]
    if len(tabs) != 1:
        raise TopologyError("REFRESH_MAIN_PANE_UNPROVEN: owned tab unresolved.")
    tab = tabs[0]
    panes = [pane for pane in snapshot["panes"] if pane["tab_id"] == tab["bridge_id"]]
    titles = {pane["title"] for pane in panes}
    # Workers are chained (each splits from the previous), so walk the whole
    # subtree under MAIN, not only its direct children.
    everyone = {w["id"]: w for w in store.workers()}
    children = []
    for candidate in everyone.values():
        cursor, seen = candidate, set()
        while cursor and cursor["id"] not in seen:
            seen.add(cursor["id"])
            parent_id = cursor.get("parent_id")
            if parent_id == worker["id"]:
                if candidate["state"] not in {"failed", "done", "disconnected"}:
                    children.append(candidate)
                break
            cursor = everyone.get(parent_id) if parent_id else None
    for child in children:
        certificate = (child.get("topology_json") or {}).get("certificate")
        if certificate and certificate not in titles:
            raise TopologyError("REFRESH_MAIN_PANE_UNPROVEN: owned tab lacks a live child certificate pane.")
    candidates = [pane for pane in panes if not str(pane["title"]).startswith("ORCH_")]
    if len(candidates) != 1 or candidates[0]["title"] != topology.get("pane_title"):
        raise TopologyError(f"REFRESH_MAIN_PANE_UNPROVEN: {len(candidates)} uncertified panes in the owned tab.")
    window = next(win for win in snapshot["windows"] if win["bridge_id"] == tab["window_id"])
    return {**topology, "window": window, "tab": tab, "pane": candidates[0]}


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
        hwnd = topology.get("window", {}).get("hwnd")
        if topology.get("adopted"):
            refreshed = _topology_for_adopted_refresh(store, worker, current)
        elif not certificate or certificate not in (current.get("command_line") or ""):
            raise WorkerRuntimeError("REFRESH_CERTIFICATE_PROCESS_UNPROVEN")
        else:
            refreshed = _topology_for_refresh(certificate, current, topology["window_name"], [hwnd] if hwnd else None)
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
    ref = worker.get("ref_json") or {}
    if ref.get("pid"):
        try:
            current = reference_for_pid(int(ref["pid"])).to_dict()
            if current.get("process_start_time") == ref.get("process_start_time"):
                certificate = (worker.get("topology_json") or {}).get("certificate", "")
                if certificate and certificate in (current.get("command_line") or ""):
                    # The pane host is the durable control plane.  A task or
                    # interactive-agent fault must not require catching a
                    # disappearing UIA pane in order to recover it.
                    read_console(str(current["pid"]), current["process_start_time"])
                    store.record_retry(worker_id, "in-place certified transport recovery")
                    store.update_worker(worker_id, state="recovering", ref=current,
                                        health={"reachable": True, "recovery_mode": "in_place_transport"})
                    return store.update_worker(
                        worker_id, state="ready", ref=current,
                        health={"reachable": True, "recovered_at": time.time(),
                                "recovery_mode": "in_place_transport"},
                    )
        except TargetError:
            pass
        except OSError as exc:
            raise WorkerRuntimeError(f"RECOVERY_TRANSPORT_UNREADABLE: {exc}") from exc
    # A disappeared transport has no safe pane target.  Wait for Terminal to
    # retire it naturally; do not send a close command to a redraw-prone pane.
    topology = worker.get("topology_json") or {}
    if topology:
        hwnd = topology.get("window", {}).get("hwnd")
        runtime_id = topology.get("pane", {}).get("runtime_id")
        certificate = topology.get("certificate")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd] if hwnd else None)
            remains = any(pane["runtime_id"] == runtime_id or pane.get("title") == certificate
                          for pane in snapshot["panes"])
            if not remains:
                break
            time.sleep(0.2)
        else:
            raise WorkerRuntimeError("RECOVERY_PANE_EXIT_PENDING")
    store.record_retry(worker_id, "controlled replacement")
    recovering = store.update_worker(worker_id, state="recovering", ref={}, topology={},
                                     health={"reachable": False, "reason": "replacement starting"})
    parent = None
    if worker.get("parent_id"):
        parent = store.worker(worker["parent_id"])
        if parent["state"] in {"failed", "done", "disconnected"} or not parent.get("topology_json"):
            raise WorkerRuntimeError("RECOVERY_PARENT_UNAVAILABLE")
        parent = refresh_worker_topology(store, parent["id"])
    return _launch_worker(store, recovering, engine, parent)


def send_worker(store: Store, worker_id: str, command: str, marker: str | None = None) -> dict:
    worker = store.worker(worker_id)
    if worker["state"] in {"failed", "done", "disconnected"}:
        raise WorkerRuntimeError(f"Worker {worker_id} is not writable in state {worker['state']}.")
    ref = worker["ref_json"]
    if not ref:
        raise WorkerRuntimeError(f"Worker {worker_id} has no live AgentRef.")
    result = send_console(str(ref["pid"]), command, True, marker, 5.0, ref["process_start_time"])
    store.update_worker(worker_id, state="working", health={**(worker.get("health_json") or {}), "reachable": True, "last_phase": result["phase"]})
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
                        health={**(worker.get("health_json") or {}), "reachable": True,
                                "last_phase": result["phase"], "delivery": "input"})
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
    # /T: an interactive agent (claude/codex) hosted inside the certified
    # console is a child of the certified PID and must not outlive it.
    subprocess.run(["taskkill.exe", "/PID", str(ref["pid"]), "/T", "/F"], capture_output=True, text=True, timeout=15, check=False)
    store.update_worker(worker_id, state="failed", health={"reachable": False, "reason": "terminated by orchestrator"})
