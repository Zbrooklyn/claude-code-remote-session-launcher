#!/usr/bin/env python3
"""window-list.py — show recent /window spawns and which are still alive.

Reads ~/.claude/window-log.jsonl (the spawn log) and cross-references
running claude.exe processes via PowerShell. Marks each entry alive/dead.

Usage:
  python window-list.py                  # list recent spawns
  python window-list.py --tag <name>     # filter to sessions tagged <name>
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases  # noqa: E402
from window_tags import load_tags, sessions_with_tag, validate_tag  # noqa: E402

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


def format_entry(e: dict, alive_names: set[str], aliases: dict[str, str], tags: dict[str, list[str]]) -> str:
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
        alias = aliases.get(sess)
        if alias:
            parts.append(f"name={alias} (renamed from {sess})")
        else:
            parts.append(f"name={sess}")
        ts_list = tags.get(sess, [])
        if ts_list:
            parts.append(f"tags=[{', '.join(ts_list)}]")
    if e.get("worktree"):
        parts.append("worktree")
    return "  ".join(parts)


def parse_tag_filter(argv: list[str]) -> str | None:
    """If --tag <name> is present, return the tag. Else None."""
    if not argv:
        return None
    # Accept both: --tag mytag (separate args)  and  "--tag mytag" (single string)
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    for i, tok in enumerate(flat):
        if tok == "--tag" and i + 1 < len(flat):
            return flat[i + 1]
    return None


def main() -> int:
    tag_filter = parse_tag_filter(sys.argv[1:])
    if tag_filter is not None:
        ok, err = validate_tag(tag_filter)
        if not ok:
            print(f"Bad --tag value: {err}", file=sys.stderr)
            return 2

    entries = load_log(limit=30)
    if not entries:
        print("No spawns logged yet. Try /window first.")
        return 0
    alive = running_session_names()
    aliases = load_aliases()
    tags = load_tags()

    if tag_filter:
        allowed = set(sessions_with_tag(tag_filter, tags))
        entries = [e for e in entries if (e.get("session_name") or "") in allowed]
        if not entries:
            print(f"No spawns match tag '{tag_filter}'.")
            print()
            print(f"To add a session to this tag:")
            print(f"  /window-tag <session-name> {tag_filter}")
            return 0
        print(f"Spawns tagged '{tag_filter}' ({len(entries)}):\n")
    else:
        print(f"Recent spawns (last {len(entries)}, newest at bottom):\n")

    for e in entries:
        print(format_entry(e, alive, aliases, tags))
    print()
    alive_count = sum(
        1 for e in entries if e.get("session_name") and e["session_name"] in alive
    )
    print(f"Alive remote-controlled sessions: {alive_count}")
    if aliases:
        print(
            "\nNote: renamed names are LOCAL aliases only. claude.ai/code and the "
            "mobile app still show each session's original --remote-control name."
        )
    if tags and not tag_filter:
        print(
            "\nTags are LOCAL too. Filter to a group with /window-list --tag <name>."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
