#!/usr/bin/env python3
"""Stable, process-grounded identities for native console targets.

PID alone is never a durable address.  Every mutating operation re-reads the
process table and requires the same PID, creation time, and executable image.
WT_SESSION is useful Windows Terminal context when the process exposes it, but
is deliberately enrichment rather than the authority for console targeting.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class TargetError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_CONSOLE_IMAGES = {"powershell.exe", "pwsh.exe", "claude.exe"}


@dataclass(frozen=True)
class AgentRef:
    pid: int
    process_start_time: str
    process_image: str | None
    parent_pid: int | None = None
    command_line: str | None = None
    wt_session: str | None = None
    claude_session_id: str | None = None
    remote_control_name: str | None = None
    alias: str | None = None
    cwd: str | None = None
    status: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _powershell_processes(pid: int | None = None) -> list[dict]:
    """Return the PowerShell/Claude process facts from WMI, never a shell guess."""
    if sys.platform != "win32":
        return []
    filt = "Name='powershell.exe' OR Name='pwsh.exe' OR Name='claude.exe'"
    if pid is not None:
        filt = f"ProcessId={int(pid)}"
    cmd = (
        "$p=Get-CimInstance Win32_Process -Filter \"%s\";"
        "$p|Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate|"
        "ConvertTo-Json -Compress" % filt
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=15, check=False,
        )
        data = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    return [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])


def _remote_environment(pid: int) -> str | None:
    """Read a same-bitness process environment block and return WT_SESSION.

    This is intentionally best effort: protected/cross-bitness processes still
    receive a valid AgentRef, simply without Windows Terminal enrichment.
    """
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
    handle = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None
    try:
        class PBI(ctypes.Structure):
            _fields_ = [("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
                       ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_void_p),
                       ("Reserved3", ctypes.c_void_p)]
        pbi = PBI()
        returned = ctypes.c_ulong()
        if ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(returned)) != 0:
            return None
        def read(addr: int, size: int) -> bytes | None:
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t()
            if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
                return None
            return buf.raw[:got.value]
        peb = read(int(pbi.PebBaseAddress), 0x28)
        if not peb:
            return None
        params = int.from_bytes(peb[0x20:0x28], "little")
        raw = read(params + 0x80, 8)
        if not raw:
            return None
        environment = int.from_bytes(raw, "little")
        block = read(environment, 131072)
        if not block:
            return None
        text = block.decode("utf-16-le", errors="ignore")
        for entry in text.split("\x00"):
            if entry.upper().startswith("WT_SESSION="):
                return entry.partition("=")[2] or None
    finally:
        k32.CloseHandle(handle)
    return None


def _ref_from_process(p: dict, enrich: bool = True) -> AgentRef:
    pid = int(p["ProcessId"])
    return AgentRef(
        pid=pid,
        process_start_time=str(p.get("CreationDate") or ""),
        process_image=p.get("ExecutablePath") or p.get("Name"),
        parent_pid=int(p["ParentProcessId"]) if p.get("ParentProcessId") is not None else None,
        command_line=p.get("CommandLine"),
        wt_session=_remote_environment(pid) if enrich else None,
    )


def list_power_shells() -> list[AgentRef]:
    return [_ref_from_process(p) for p in _powershell_processes()
            if str(p.get("Name", "")).lower() in _CONSOLE_IMAGES]


def reference_for_pid(pid: int) -> AgentRef:
    rows = _powershell_processes(pid)
    if not rows:
        raise TargetError("NOT_FOUND", f"No process with PID {pid} exists.")
    p = rows[0]
    if str(p.get("Name", "")).lower() not in _CONSOLE_IMAGES:
        raise TargetError("NOT_A_CONSOLE_TARGET", f"PID {pid} is not PowerShell or Claude Code.")
    ref = _ref_from_process(p)
    if not ref.process_start_time:
        raise TargetError("IDENTITY_UNAVAILABLE", f"Could not read a creation time for PID {pid}.")
    return ref


def resolve_target(value: str) -> AgentRef:
    """Resolve a PID or existing launcher alias/remote-control session name."""
    try:
        return reference_for_pid(int(value))
    except ValueError:
        pass
    from window_aliases import load_aliases, resolve_to_actual
    from agents_state import by_remote_control_name
    actual = resolve_to_actual(value, load_aliases())
    agent = by_remote_control_name().get(actual)
    if not agent or not agent.get("pid"):
        raise TargetError("NOT_FOUND", f"No live PowerShell or Claude target named {value!r}.")
    ref = reference_for_pid(int(agent["pid"]))
    return AgentRef(**{**ref.to_dict(), "claude_session_id": agent.get("sessionId"),
                       "remote_control_name": actual, "alias": value if actual != value else None,
                       "cwd": agent.get("cwd"), "status": agent.get("status")})


def validate_target(ref: AgentRef) -> AgentRef:
    """Reject disappeared or PID-reused targets immediately before I/O."""
    try:
        current = reference_for_pid(ref.pid)
    except TargetError as exc:
        raise TargetError("STALE_TARGET", f"Target PID {ref.pid} is gone.") from exc
    if current.process_start_time != ref.process_start_time:
        raise TargetError("STALE_TARGET", f"PID {ref.pid} was reused (start time changed).")
    if (current.process_image or "").lower() != (ref.process_image or "").lower():
        raise TargetError("STALE_TARGET", f"PID {ref.pid} executable identity changed.")
    return AgentRef(**{**ref.to_dict(), "wt_session": current.wt_session or ref.wt_session})
