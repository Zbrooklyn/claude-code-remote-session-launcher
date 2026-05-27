#!/usr/bin/env python3
"""window-find.py -- look up whether a session about <topic> already exists,
BEFORE spawning a new one.

This is the "look first" half of the find-or-confirm-or-ask protocol (see the
README). An agent about to open a session for some topic should run this first:

  - If matches exist, this lists them (each marked alive or dead) and prints the
    exact command to resume the best one -- but it does NOT resume. The agent is
    expected to confirm with the user which to resume (or to spawn new), then run
    /window-resume <id> (or /window ...). That confirmation step is the gate.
  - If nothing matches, it says so and prints the command to start fresh -- again
    without acting.

By never spawning or resuming itself, this command structurally enforces the
"ask before you act" rule instead of relying on the agent to remember it. A
human who already knows what they want can skip this and call /window-resume
directly.

Usage:
  python window-find.py <topic> [--days N] [--limit N] [--json]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_sessions import (  # noqa: E402
    list_resumable, find_by_name, is_ambiguous, alive_session_ids,
)


def parse_argv(argv: list[str]) -> dict:
    opts = {"topic": None, "days": 14, "limit": 8, "json": False}
    i = 0
    while i < len(argv):
        t = argv[i]
        if t == "--days" and i + 1 < len(argv):
            try:
                opts["days"] = int(argv[i + 1])
            except ValueError:
                print(f"ERROR: --days needs an integer, got {argv[i+1]!r}", file=sys.stderr)
                sys.exit(2)
            i += 2; continue
        if t == "--limit" and i + 1 < len(argv):
            try:
                opts["limit"] = int(argv[i + 1])
            except ValueError:
                print(f"ERROR: --limit needs an integer, got {argv[i+1]!r}", file=sys.stderr)
                sys.exit(2)
            i += 2; continue
        if t == "--json":
            opts["json"] = True; i += 1; continue
        if t.startswith("--"):
            i += 1; continue
        if opts["topic"] is None:
            opts["topic"] = t
        i += 1
    return opts


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: window-find.py <topic> [--days N] [--limit N] [--json]", file=sys.stderr)
        return 2
    opts = parse_argv(argv)
    if not opts["topic"]:
        print("ERROR: provide a topic to search for.", file=sys.stderr)
        return 2
    topic = opts["topic"]

    candidates = list_resumable(max_age_days=opts["days"])
    matches = find_by_name(topic, candidates)
    alive = alive_session_ids()
    ranked = matches[: opts["limit"]]

    if opts["json"]:
        payload = {
            "topic": topic,
            "found": len(matches),
            "ambiguous": is_ambiguous(matches),
            "candidates": [
                {
                    "session_id": c.session_id,
                    "name": (c.labels[0] if c.labels else None),
                    "description": c.first_prompt,
                    "workspace": c.cwd,
                    "permission_mode": c.permission_mode,
                    "alive": c.session_id in alive,
                    "score": round(score, 1),
                }
                for score, c in ranked
            ],
            # The gate: this tool never acts. It tells the caller the next step.
            "next_step": (
                "confirm_with_user_then_resume" if matches else "confirm_with_user_then_spawn"
            ),
            "resume_command": (
                f"/window-resume {ranked[0][1].session_id}" if matches else None
            ),
            "spawn_hint": "/window <workspace> \"<first prompt>\"  (or /window-remote / /window-yolo-remote)",
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not matches:
        print(f"No existing session matches {topic!r} (looked back {opts['days']} days).")
        print()
        print("This looks like a NEW session. Confirm with the user, then start one:")
        print('  /window <workspace> "<first prompt>"       (standard perms)')
        print('  /window-remote ...                         (also reachable from web/app)')
        print('  /window-yolo-remote ...                    (autonomous worker)')
        return 0

    n = len(matches)
    print(f"Found {n} session(s) matching {topic!r}:")
    print()
    print(f"  {'ST':4}  {'ID':10}  {'PERM':>4}  {'NAME':24}  WORKSPACE / DESC")
    print("  " + "-" * 110)
    for score, c in ranked:
        st = "live" if c.session_id in alive else "off"
        perm = {"bypassPermissions": "YOLO"}.get(c.permission_mode or "", (c.permission_mode or "def")[:4])
        name = (c.labels[0] if c.labels else "(no label)")[:24]
        tail = (c.cwd or "")[-30:] + "  /  " + (c.first_prompt or "")[:44]
        print(f"  {st:4}  {c.session_id[:10]}  {perm:>4}  {name:24}  {tail}")
    print()

    if is_ambiguous(matches):
        print("Top matches are close -- do NOT auto-pick. Confirm with the user which one,")
        print("then resume it by its session-id prefix:")
        print(f"  /window-resume {ranked[0][1].session_id[:8]}")
    else:
        best = ranked[0][1]
        state = "already live" if best.session_id in alive else "resumable"
        print(f"Best match ({state}). Confirm with the user, then:")
        if best.session_id in alive:
            lbl = best.labels[0] if best.labels else best.session_id[:8]
            print(f"  /window-attach {lbl}      (it's already running -- attach, don't duplicate)")
        else:
            print(f"  /window-resume {best.session_id[:8]}")
    print()
    print("Or, if none of these is the right session, confirm and start a new one with /window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
