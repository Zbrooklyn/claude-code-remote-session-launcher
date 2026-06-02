#!/usr/bin/env python3
"""window-resume-all.py -- preview and relaunch a CURATED SET of past sessions.

Where /window-resume reopens one session, this reopens a whole set in one shot:
your "resume all my conversations" set, optionally filtered by theme / project /
state. It is the orchestrator; the actual relaunch of each session is delegated
to window-resume.py (original cwd, original permission mode, remote control, and
a dup-guard that skips anything already running).

The set comes from a catalog file -- an array of records, each needing at least
`id` and `launch` (bool), and optionally `name`/`window_alias`, `size`, `model`,
`parent_theme`, `project_slug`, `state`. Catalog resolution, in order:
  1. $CLAUDE_RESUME_CATALOG, if set and present.
  2. <default_workspace>/conversations.json   (default_workspace from window-config.json)
  3. ~/.claude/resume-set.json                 (generic fallback)
This keeps the launcher portable: on a machine with a rich catalog it uses it;
elsewhere a simple resume-set.json works.

Usage:
  python window-resume-all.py [--go] [--all | --theme T | --slug S | --state ST] [--stagger N]
    (no --go)  preview only: the set, what's already running, what's heavy
    --go       actually resume the not-already-running members of the set
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from claude_env import claude_home  # noqa: E402
try:
    from window_sessions import alive_pid_for_session  # noqa: E402
except Exception:
    def alive_pid_for_session(_sid):
        return None

WINDOW_RESUME = HERE / "window-resume.py"


def find_catalog() -> Path | None:
    env = os.environ.get("CLAUDE_RESUME_CATALOG")
    if env and Path(env).expanduser().exists():
        return Path(env).expanduser()
    cfg = claude_home() / "window-config.json"
    try:
        ws = json.load(open(cfg, encoding="utf-8")).get("default_workspace")
        if ws:
            cand = Path(ws) / "conversations.json"
            if cand.exists():
                return cand
    except Exception:
        pass
    rs = claude_home() / "resume-set.json"
    return rs if rs.exists() else None


def parse_size_mb(size_str) -> float:
    try:
        n = float(str(size_str).split()[0])
        return n / 1024 if str(size_str).strip().endswith("KB") else n
    except Exception:
        return 0.0


def label_of(r) -> str:
    return r.get("window_alias") or r.get("name") or (r.get("id", "")[:8])


def load_set(cat: Path, opts) -> list:
    recs = json.load(open(cat, encoding="utf-8"))
    if isinstance(recs, dict) and "sessions" in recs:
        recs = recs["sessions"]
    sel = [r for r in recs if r.get("launch")]
    if opts["theme"]:
        sel = [r for r in sel if opts["theme"].lower() in str(r.get("parent_theme", "")).lower()]
    if opts["slug"]:
        sel = [r for r in sel if opts["slug"].lower() in str(r.get("project_slug", "")).lower()]
    if opts["state"]:
        sel = [r for r in sel if opts["state"].lower() in str(r.get("state", "")).lower()]
    return sel


def annotate(sel) -> list:
    for r in sel:
        r["_alive_pid"] = alive_pid_for_session(r.get("id", ""))
        r["_size_mb"] = parse_size_mb(r.get("size", "0 KB"))
    return sel


def preview(sel, filt_desc) -> int:
    if not sel:
        print(f"No flagged sessions match {filt_desc}.")
        print("Mark a session with `launch: true` in your catalog to include it.")
        return 1
    alive = [r for r in sel if r["_alive_pid"]]
    todo = [r for r in sel if not r["_alive_pid"]]
    heavy = [r for r in todo if r["_size_mb"] >= 50]
    print(f"/window-resume-all -- {filt_desc}")
    print(f"{len(todo)} to launch | {len(alive)} already running (skip) | {len(heavy)} heavy (>50MB, slow)\n")
    w = max((len(label_of(r)) for r in sel), default=6)
    for i, r in enumerate(sel, 1):
        flag = "RUNNING" if r["_alive_pid"] else ("HEAVY  " if r["_size_mb"] >= 50 else "launch ")
        print(f"{i:>2}. [{flag}] {label_of(r):<{w}}  {str(r.get('size','')):>8}  {str(r.get('model','')):<10}  {r.get('name','')}")
    if todo:
        print(f"\nAdd --go to resume the {len(todo)} not-already-running session(s).")
    else:
        print("\nEverything in the set is already running -- nothing to launch.")
    return 0


def launch(sel, stagger) -> int:
    todo = [r for r in sel if not r["_alive_pid"]]
    skipped = [r for r in sel if r["_alive_pid"]]
    for r in skipped:
        print(f"[skip] {label_of(r)} already running (pid {r['_alive_pid']}).")
    if not todo:
        print("Nothing to launch -- everything in the set is already running.")
        return 0
    failed = []
    for i, r in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] resuming {label_of(r)} ({r.get('id','')[:8]}) -- {r.get('name','')}")
        try:
            res = subprocess.run(
                [sys.executable, str(WINDOW_RESUME), r["id"], "--no-verify"],
                capture_output=True, text=True, timeout=60,
            )
            out = (res.stdout + res.stderr).strip()
            print("   " + (out.splitlines()[0] if out else "(no output)"))
            if res.returncode != 0:
                failed.append(r)
        except subprocess.TimeoutExpired:
            print("   ERROR: window-resume timed out")
            failed.append(r)
        if i < len(todo):
            time.sleep(stagger)
    print("\nWaiting for sessions to come alive...")
    time.sleep(8)
    not_yet = [r for r in todo if not alive_pid_for_session(r["id"])]
    alive_now = len(todo) - len(not_yet)
    print("\n=== resume-all report ===")
    print(f"launched & alive: {alive_now}  |  skipped (already running): {len(skipped)}  |  not-yet-alive: {len(not_yet)}")
    for r in not_yet:
        print(f"  still loading / check: {label_of(r)} ({r.get('id','')[:8]}) -- {r.get('size','')}")
    print("\nSee all with /window-live. Each resumed session is remote-reachable from claude.ai/code + mobile.")
    return 1 if failed else 0


def main() -> int:
    argv = sys.argv[1:]
    opts = {"go": False, "theme": None, "slug": None, "state": None, "stagger": 2.0}
    i = 0
    while i < len(argv):
        t = argv[i]
        if t in ("--go", "--launch"):
            opts["go"] = True; i += 1
        elif t == "--all":
            i += 1
        elif t in ("--theme", "--slug", "--state") and i + 1 < len(argv):
            opts[t[2:]] = argv[i + 1]; i += 2
        elif t == "--stagger" and i + 1 < len(argv):
            try:
                opts["stagger"] = float(argv[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    cat = find_catalog()
    if not cat:
        print("ERROR: no resume catalog found. Looked for $CLAUDE_RESUME_CATALOG, "
              "<default_workspace>/conversations.json, and ~/.claude/resume-set.json.", file=sys.stderr)
        return 2

    parts = [d for d in (
        ("theme=" + opts["theme"]) if opts["theme"] else None,
        ("slug=" + opts["slug"]) if opts["slug"] else None,
        ("state=" + opts["state"]) if opts["state"] else None,
    ) if d]
    filt_desc = "all flagged sessions" if not parts else ", ".join(parts)

    sel = annotate(load_set(cat, opts))
    return launch(sel, opts["stagger"]) if opts["go"] else preview(sel, filt_desc)


if __name__ == "__main__":
    sys.exit(main())
