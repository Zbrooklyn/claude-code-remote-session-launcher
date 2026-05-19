#!/usr/bin/env python3
"""window-kill.py — terminate a spawned Claude session by session name.

Usage:
  python window-kill.py <session-name>
  python window-kill.py --all           # kill all spawned sessions
"""
from __future__ import annotations
import subprocess
import sys


def find_pids_by_session_name(name: str | None) -> list[tuple[int, str]]:
    """Return list of (pid, command_line_snippet) for matching claude.exe processes."""
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
        return []
    import json as _json
    try:
        data = _json.loads(result.stdout)
    except _json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    matches: list[tuple[int, str]] = []
    for entry in data:
        cmd = entry.get("CommandLine") or ""
        pid = entry.get("ProcessId")
        if "--remote-control" not in cmd:
            continue
        if name is None or name in cmd:
            matches.append((int(pid), cmd))
    return matches


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: window-kill.py <session-name>  OR  window-kill.py --all", file=sys.stderr)
        return 2
    target = sys.argv[1]
    if target == "--all":
        matches = find_pids_by_session_name(None)
    else:
        matches = find_pids_by_session_name(target)

    if not matches:
        print(f"No matching sessions found for: {target}")
        return 1

    print(f"About to kill {len(matches)} session(s):")
    for pid, cmd in matches:
        snippet = cmd[:120] + ("..." if len(cmd) > 120 else "")
        print(f"  PID {pid}: {snippet}")

    killed = 0
    for pid, _ in matches:
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
                check=True, timeout=5,
            )
            killed += 1
        except subprocess.SubprocessError as e:
            print(f"  FAILED to kill PID {pid}: {e}", file=sys.stderr)

    print(f"Killed {killed}/{len(matches)}.")
    return 0 if killed == len(matches) else 1


if __name__ == "__main__":
    sys.exit(main())
