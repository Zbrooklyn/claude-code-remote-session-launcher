#!/usr/bin/env python3
"""agents_state.py — shared wrapper around `claude agents --json`.

Returns the live-session inventory Anthropic's CLI exposes: pid, cwd,
kind, sessionId, optional display name, status (idle/busy), startedAt.

This is the canonical "what's actually running" view — richer than
parsing Win32_Process command lines, because it includes idle/busy
state, the conversation's session ID, and any -n display name.

Note: `name` in this output is Claude's -n / display-name field. It is
DIFFERENT from the --remote-control name (which is what our /window
family uses to address sessions). Sessions launched via /window-yolo-remote
do NOT set -n, so they typically have no `name` here.

We correlate to remote-control sessions by reading the running process
command line separately and matching on pid.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from claude_env import find_claude_binary  # noqa: E402


def fetch_agents(timeout_s: float = 10.0) -> list[dict[str, Any]]:
    """Return the list from `claude agents --json`. Empty list on failure."""
    claude = find_claude_binary()
    if not claude:
        return []
    try:
        result = subprocess.run(
            [claude, "agents", "--json"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


def remote_control_map() -> dict[int, str]:
    """Map pid -> --remote-control name for each running claude.exe."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = [data]
    out: dict[int, str] = {}
    for entry in data:
        cmd = entry.get("CommandLine") or ""
        pid = entry.get("ProcessId")
        if pid is None or "--remote-control" not in cmd:
            continue
        toks = cmd.split()
        for i, tok in enumerate(toks):
            if tok == "--remote-control" and i + 1 < len(toks):
                out[int(pid)] = toks[i + 1].strip('"')
                break
    return out


def by_remote_control_name() -> dict[str, dict[str, Any]]:
    """Return {remote_control_name: agent_state_dict} for every live
    --remote-control session. Sessions without --remote-control are
    omitted (they can't be addressed by the /window family anyway).
    """
    pid_to_name = remote_control_map()
    if not pid_to_name:
        return {}
    agents = fetch_agents()
    out: dict[str, dict[str, Any]] = {}
    for a in agents:
        pid = a.get("pid")
        if pid in pid_to_name:
            out[pid_to_name[pid]] = a
    return out


def format_age(started_at_ms: int | None, now_ms: int | None = None) -> str:
    """Render epoch-ms startedAt as a compact age (1h 23m, 3d 4h, etc)."""
    if not started_at_ms:
        return "?"
    import time
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    delta_s = max(0, (now_ms - started_at_ms) // 1000)
    days, rem = divmod(delta_s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    if mins:
        return f"{mins}m"
    return f"{delta_s}s"
