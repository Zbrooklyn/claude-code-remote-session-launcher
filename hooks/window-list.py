#!/usr/bin/env python3
"""window-list.py — show recent /window spawns and which are still alive.

Reads ~/.claude/window-log.jsonl (the spawn log) and cross-references
running claude.exe processes via PowerShell. Marks each entry alive/dead.
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "window-log.jsonl"


def load_log(limit: int = 30) -> list[dict]:
    if not LOG_PATH.is_file():
        return []
    entries: list[dict] = []
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries[-limit:]


def running_session_names() -> set[str]:
    """Return set of --remote-control session names currently running."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        if "--remote-control" not in line:
            continue
        toks = line.split()
        for i, tok in enumerate(toks):
            if tok == "--remote-control" and i + 1 < len(toks):
                names.add(toks[i + 1].strip('"'))
                break
    return names


def format_entry(e: dict, alive_names: set[str]) -> str:
    ts = e.get("timestamp", "?")
    mode = e.get("mode", "?")
    workspace = e.get("workspace", "?")
    sess = e.get("session_name") or ""
    if sess:
        status = "ALIVE" if sess in alive_names else "dead"
    else:
        status = "local-only (no remote name to track)"
    short_ws = Path(workspace).name if workspace and workspace != "?" else "?"
    parts = [f"{ts}", f"[{status}]", f"{mode}", f"in {short_ws}"]
    if sess:
        parts.append(f"name={sess}")
    if e.get("worktree"):
        parts.append("worktree")
    return "  ".join(parts)


def main() -> int:
    entries = load_log(limit=30)
    if not entries:
        print("No spawns logged yet. Try /window first.")
        return 0
    alive = running_session_names()
    print(f"Recent spawns (last {len(entries)}, newest at bottom):\n")
    for e in entries:
        print(format_entry(e, alive))
    print()
    alive_count = sum(
        1 for e in entries if e.get("session_name") and e["session_name"] in alive
    )
    print(f"Alive remote-controlled sessions: {alive_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
