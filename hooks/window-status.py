#!/usr/bin/env python3
"""window-status.py -- show a spawned session's live state.

Usage:
  python window-status.py <session-name-or-alias>
  python window-status.py --all                  # one line per live session
  python window-status.py --busy                 # only busy sessions
  python window-status.py --idle                 # only idle sessions

Reports: status (idle/busy), age since spawn, cwd, sessionId, and any
tags or alias set locally. Uses `claude agents --json` for the live
state (status is the value the official mobile/web app sees).

This is the foundation of HEAR-BACK -- knowing if a delegated session
has finished its work and gone idle, vs. still chewing on it.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual, display_for  # noqa: E402
from window_tags import load_tags  # noqa: E402
from agents_state import by_remote_control_name, format_age  # noqa: E402


def render_one(name: str, agent: dict, aliases: dict[str, str], tags: dict[str, list[str]], verbose: bool) -> str:
    status = agent.get("status", "?")
    age = format_age(agent.get("startedAt"))
    cwd_short = Path(agent.get("cwd", "?")).name if agent.get("cwd") else "?"
    parts = [f"[{status}]", name, f"age={age}", f"in {cwd_short}"]
    alias = display_for(name, aliases)
    if alias:
        parts.append(f"alias={alias}")
    ts = tags.get(name) or []
    if ts:
        parts.append(f"tags=[{', '.join(ts)}]")
    line = "  ".join(parts)
    if not verbose:
        return line
    extras = [
        f"  sessionId: {agent.get('sessionId', '?')}",
        f"  pid:       {agent.get('pid', '?')}",
        f"  cwd:       {agent.get('cwd', '?')}",
    ]
    return line + "\n" + "\n".join(extras)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: window-status.py <session-name-or-alias>", file=sys.stderr)
        print("       window-status.py --all|--busy|--idle", file=sys.stderr)
        return 2
    # Accept single-token "$ARGUMENTS" forms
    if len(args) == 1 and " " in args[0]:
        args = args[0].split()

    live = by_remote_control_name()
    aliases = load_aliases()
    tags = load_tags()

    filter_status: str | None = None
    if args[0] in ("--all", "--busy", "--idle"):
        flag = args[0]
        if flag == "--busy":
            filter_status = "busy"
        elif flag == "--idle":
            filter_status = "idle"
        # --all leaves filter_status=None

        if not live:
            print("No live --remote-control sessions.")
            return 0
        rows = []
        for name in sorted(live):
            a = live[name]
            if filter_status and a.get("status") != filter_status:
                continue
            rows.append(render_one(name, a, aliases, tags, verbose=False))
        if not rows:
            label = filter_status or "any"
            print(f"No live sessions with status '{label}'.")
            return 0
        title = {
            "busy": "Busy sessions",
            "idle": "Idle sessions",
            None: "Live sessions",
        }[filter_status]
        print(f"{title} ({len(rows)}):")
        print()
        for r in rows:
            print(r)
        return 0

    # Single session lookup
    target = args[0]
    actual = resolve_to_actual(target, aliases)
    if actual != target:
        print(f"Resolved alias '{target}' -> '{actual}'")
    a = live.get(actual)
    if not a:
        print(f"No live session named '{actual}'.")
        print("Run /window-list to see what's running, or /window-status --all.")
        return 1
    print(render_one(actual, a, aliases, tags, verbose=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
