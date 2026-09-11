#!/usr/bin/env python3
"""Resolve the pane-host PID of the Claude/Codex session that owns this process.

The orchestrator CLI runs as a short-lived child of the MAIN session that
invoked it (python -> claude.exe -> powershell.exe -> WindowsTerminal.exe).
Adopting MAIN needs the pane host, which is the PowerShell process hosting the
MAIN agent's console.  This walks the real parent chain with the Toolhelp
snapshot API so a user never has to find or type a PID.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

_CONSOLE_HOSTS = {"powershell.exe", "pwsh.exe"}
_AGENTS = {"claude.exe", "codex.exe"}


def _process_table() -> dict[int, dict]:
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap == -1:
        raise OSError("CreateToolhelp32Snapshot failed")
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    table: dict[int, dict] = {}
    try:
        if k32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                table[entry.th32ProcessID] = {"ppid": entry.th32ParentProcessID,
                                              "name": entry.szExeFile.lower()}
                if not k32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        k32.CloseHandle(snap)
    return table


def ancestry(pid: int | None = None) -> list[dict]:
    """This process and each ancestor, nearest first, as {pid, name}."""
    table = _process_table()
    pid = pid if pid is not None else os.getpid()
    chain, seen = [], set()
    while pid and pid in table and pid not in seen:
        seen.add(pid)
        chain.append({"pid": pid, "name": table[pid]["name"]})
        pid = table[pid]["ppid"]
    return chain


def main_pane_host_pid(pid: int | None = None) -> int:
    """The PowerShell pane host of the nearest agent (claude/codex) ancestor.

    Prefer the console host directly above the nearest agent process; fall back
    to the nearest console host in the chain.  Raising here is correct: MAIN
    must be an agent session running in a PowerShell pane, and if this process
    was not launched from one we must not guess a PID.
    """
    chain = ancestry(pid)
    for index, node in enumerate(chain):
        if node["name"] in _AGENTS:
            for ancestor in chain[index + 1:]:
                if ancestor["name"] in _CONSOLE_HOSTS:
                    return ancestor["pid"]
    for node in chain:
        if node["name"] in _CONSOLE_HOSTS:
            return node["pid"]
    raise OSError("no PowerShell pane host found in this process's ancestry; "
                  "run this from inside a MAIN agent session")
