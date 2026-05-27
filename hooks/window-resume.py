#!/usr/bin/env python3
"""window-resume.py -- reopen an existing Claude Code session by name.

Usage:
  python window-resume.py <session-name-or-query> [--mode MODE] [--print] [--no-verify]

Finds a past session by fuzzy-matching <query> against spawn labels and the
session's first user prompt (shared catalog logic lives in window_sessions.py),
then reopens it with `claude --resume <id>` in its ORIGINAL workspace, preserving
its ORIGINAL permission mode.

How it stays dependable:
  - Workspace is read from the transcript's own `cwd` field -- never decoded from
    the project-dir slug (that decode is lossy and silently resumes in the wrong
    directory, which makes the session die on launch).
  - Permission mode is taken from the transcript's first permission-mode event to
    decide window-remote vs window-yolo-remote, then VERIFIED from the live
    process command line after launch (the transcript can lag; the process cmdline
    is ground truth).
  - A YOLO session comes back YOLO: spawn routes through window-yolo-remote, which
    passes --dangerously-skip-permissions. (Permission mode IS preserved on resume
    when the flag is passed -- there is no Anthropic-side downgrade.)
  - If the session is already alive, we refuse to spawn a duplicate and point you
    at /window-attach instead.
  - Liveness check after spawn has a generous timeout (25s, 40s on retry) because
    large transcripts take many seconds to load, and retries once on a miss.

The launch itself is delegated to spawn-window.py (the shared launcher) so resume
reuses the exact same trust-check, terminal-spawn, and logging as every other
/window command. This file only decides WHICH session and HOW.
"""
from __future__ import annotations
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import validate_label  # noqa: E402
from window_sessions import (  # noqa: E402
    list_resumable, find_by_name, is_ambiguous, alive_pid_for_session, slug,
)

SPAWN_WINDOW = Path(__file__).parent / "spawn-window.py"


# ---------- permission verification (process = ground truth) ----------

def _await_liveness(sid: str, timeout_s: float) -> int | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pid = alive_pid_for_session(sid)
        if pid:
            return pid
        time.sleep(0.5)
    return None


def _verify_permission_mode_from_process(pid: int) -> str | None:
    """Ground truth for a live session's permission mode: its process cmdline.
    The transcript's permission-mode events can lag and mislead; the command
    line the process was launched with cannot."""
    if not pid:
        return None
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                capture_output=True, text=True, timeout=8,
            )
            cmdline = result.stdout or ""
        else:
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
            except FileNotFoundError:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    capture_output=True, text=True, timeout=8,
                )
                cmdline = result.stdout or ""
        if not cmdline.strip():
            return None
        if "--dangerously-skip-permissions" in cmdline:
            return "bypassPermissions"
        m = re.search(r"--permission-mode\s+(\S+)", cmdline)
        return m.group(1) if m else "default"
    except Exception:
        return None


def _report_alive(pid: int, was_yolo: bool) -> int:
    """Print the liveness/permission verdict for a resumed session and return an
    exit code (0 OK, 1 if a YOLO session came back without bypassPermissions)."""
    actual = _verify_permission_mode_from_process(pid)
    verdict, note = "OK", ""
    if was_yolo and actual != "bypassPermissions":
        verdict = "WARN"
        note = f" (expected bypassPermissions, process shows {actual})"
    print(f"[{verdict}] alive (pid {pid}) -- verified perm from process: {actual}{note}")
    return 0 if verdict == "OK" else 1


def _spawn_and_verify(mode: str, args_str: str, sid: str, was_yolo: bool,
                      verify: bool, *, first_timeout: float = 45,
                      retry_timeout: float = 40, retries: int = 1) -> int:
    """Spawn the resume window (delegating to spawn-window.py) and confirm the
    session comes back alive.

    Retries once on a miss, but RE-CHECKS liveness before re-spawning: a slow
    claude cold-boot can exceed the first liveness timeout, so the prior spawn
    may have registered during the wait. Re-checking first means a slow boot
    never produces a second window onto the same session."""
    spawned = False
    for attempt in range(retries + 1):
        if spawned:
            pid = alive_pid_for_session(sid)
            if pid:
                return _report_alive(pid, was_yolo)

        try:
            result = subprocess.run(
                [sys.executable, str(SPAWN_WINDOW), mode, args_str],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: spawn-window.py timed out after 30s.", file=sys.stderr)
            return 1
        out = (result.stdout + result.stderr).strip()
        launched = result.returncode == 0 and ("Resumed" in out or "Launched" in out)
        if not launched:
            print(out or "(no output from spawn-window.py)")
            if attempt < retries:
                time.sleep(3)
                continue
            print(f"FAILED to resume {sid[:8]}.", file=sys.stderr)
            return 1
        spawned = True
        print(out.splitlines()[0] if out else "(spawned)")

        if not verify:
            return 0

        # Generous first wait: loading a large transcript and showing up in the
        # process table can take 30s+. Too short here causes the spurious retry.
        timeout = first_timeout if attempt == 0 else retry_timeout
        pid = _await_liveness(sid, timeout)
        if pid:
            return _report_alive(pid, was_yolo)
        if attempt < retries:
            print("not alive yet, re-checking liveness before any retry...")
            time.sleep(2)
            continue

    print(f"WARN: spawned but did not see a live pid for {sid[:8]} "
          f"within the timeout. It may still be loading -- check /window-list.",
          file=sys.stderr)
    return 1


# ---------- arg parsing ----------

def parse_argv(argv: list[str]) -> dict:
    opts = {"query": None, "mode": "auto", "print": False, "verify": True, "days": 14}
    i = 0
    while i < len(argv):
        t = argv[i]
        if t == "--mode" and i + 1 < len(argv):
            opts["mode"] = argv[i + 1]; i += 2; continue
        if t == "--print":
            opts["print"] = True; i += 1; continue
        if t == "--no-verify":
            opts["verify"] = False; i += 1; continue
        if t == "--days" and i + 1 < len(argv):
            try:
                opts["days"] = int(argv[i + 1])
            except ValueError:
                print(f"ERROR: --days needs an integer, got {argv[i+1]!r}", file=sys.stderr)
                sys.exit(2)
            i += 2; continue
        if t.startswith("--"):
            i += 1; continue
        if opts["query"] is None:
            opts["query"] = t
        i += 1
    return opts


# ---------- main ----------

def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: window-resume.py <session-name-or-query> [--mode MODE] [--print] [--no-verify]", file=sys.stderr)
        return 2
    opts = parse_argv(argv)
    if not opts["query"]:
        print("ERROR: provide a session name or query to resume.", file=sys.stderr)
        return 2
    query = opts["query"]

    candidates = list_resumable(max_age_days=opts["days"])
    if not candidates:
        print(f"No resumable sessions found in the last {opts['days']} days.")
        return 1

    matches = find_by_name(query, candidates)
    if not matches:
        print(f"No session matches {query!r}.")
        print("Try /window-list to see live sessions, or widen with --days N.")
        return 1

    if is_ambiguous(matches):
        print(f"Ambiguous: {query!r} matches multiple sessions about equally:")
        for score, c in matches[:5]:
            lbl = c.labels[0] if c.labels else "(no label)"
            print(f"  {c.session_id[:8]}  {lbl:24}  {(c.first_prompt or '')[:50]}")
        print("Re-run with a more specific name or the session-id prefix (>=8 chars).")
        return 2

    _, cand = matches[0]

    if not cand.cwd:
        print(f"Could not determine the workspace for {cand.session_id[:8]} "
              "(no cwd in transcript). Cannot resume safely.")
        return 1

    # Already alive? Don't spawn a duplicate.
    existing_pid = alive_pid_for_session(cand.session_id)
    if existing_pid:
        print(f"Session {cand.session_id[:8]} is already alive (pid {existing_pid}).")
        lbl = cand.labels[0] if cand.labels else cand.session_id[:8]
        print(f"Use /window-attach {lbl} to bring its window forward instead of resuming.")
        return 0

    # Decide mode from the ORIGINAL permission mode, unless overridden.
    was_yolo = cand.permission_mode == "bypassPermissions"
    if opts["mode"] == "auto":
        mode = "window-yolo-remote" if was_yolo else "window-remote"
    else:
        mode = opts["mode"]

    label = cand.labels[0] if cand.labels else cand.session_id[:8]
    label = slug(label)
    ok, err = validate_label(label)
    if not ok:
        label = cand.session_id[:8]

    # spawn-window.py reassembles a quoted, space-containing path correctly, so
    # we pass the cwd as the leading positional and let the shared launcher do
    # the trust-check + terminal spawn.
    args_str = f'"{cand.cwd}" --name {label} --resume {cand.session_id}'

    if opts["print"]:
        print(f"python \"{SPAWN_WINDOW}\" {mode} '{args_str}'")
        print(f"# resolves to: claude --resume {cand.session_id}"
              f"{' --dangerously-skip-permissions' if was_yolo else ''} in {cand.cwd}")
        return 0

    print(f"Resuming {cand.session_id[:8]} ({label}) in {cand.cwd}")
    print(f"  mode: {mode}  |  original perm: {cand.permission_mode or 'default'}")

    return _spawn_and_verify(mode, args_str, cand.session_id, was_yolo, opts["verify"])


if __name__ == "__main__":
    sys.exit(main())
