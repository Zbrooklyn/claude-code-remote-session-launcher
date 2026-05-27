#!/usr/bin/env python3
"""window-resume.py -- reopen an existing Claude Code session by name.

Usage:
  python window-resume.py <session-name-or-query> [--mode MODE] [--print] [--no-verify]

Finds a past session by fuzzy-matching <query> against spawn labels and the
session's first user prompt, then reopens it with `claude --resume <id>` in its
ORIGINAL workspace, preserving its ORIGINAL permission mode.

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
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import validate_label  # noqa: E402

CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"
SESSIONS_DIR = CLAUDE_HOME / "sessions"
LOG_PATH = CLAUDE_HOME / "window-log.jsonl"
SPAWN_WINDOW = Path(__file__).parent / "spawn-window.py"


@dataclass
class Candidate:
    session_id: str
    transcript: Path
    cwd: str
    mtime: float
    first_prompt: str | None = None
    permission_mode: str | None = None   # original mode from transcript
    labels: list[str] = field(default_factory=list)


# ---------- transcript readers ----------

def _read_field_early(jsonl: Path, key: str, max_lines: int = 80) -> str | None:
    """Return the first value of a top-level `key` found in the transcript head."""
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i > max_lines:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                val = obj.get(key)
                if val:
                    return val
    except OSError:
        return None
    return None


def _read_cwd(jsonl: Path) -> str | None:
    """Authoritative workspace: the transcript's own `cwd` field."""
    cwd = _read_field_early(jsonl, "cwd")
    return cwd.replace("\\", "/") if cwd else None


def _read_original_permission_mode(jsonl: Path, max_lines: int = 200) -> str | None:
    """First permission-mode event = the mode the session was created with."""
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i > max_lines:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "permission-mode":
                    return obj.get("permissionMode")
    except OSError:
        return None
    return None


def _read_first_user_prompt(jsonl: Path, max_lines: int = 80) -> str | None:
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i > max_lines:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "user":
                    continue
                content = obj.get("message", {}).get("content")
                text = None
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text = c.get("text")
                            break
                if not text:
                    continue
                text = text.strip()
                # Skip system-injected / non-human first messages.
                if text.startswith(("<", "Caveat:", "[Request", "===", "Launched")):
                    continue
                return text[:500]
    except OSError:
        return None
    return None


# ---------- spawn-label correlation ----------

def _labels_by_session_id() -> dict[str, list[str]]:
    """Map session_id -> [labels] from the spawn log. Resume entries record the
    resume_id; fresh spawns record session_name/label only (no id), so this map
    is best-effort -- the fuzzy matcher also searches first prompts."""
    out: dict[str, list[str]] = {}
    if not LOG_PATH.is_file():
        return out
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = o.get("session_id") or o.get("resume_id")
                label = o.get("label") or o.get("name") or o.get("session_name")
                if sid and label:
                    out.setdefault(sid, [])
                    if label not in out[sid]:
                        out[sid].append(label)
    except OSError:
        pass
    return out


# ---------- catalog + match ----------

def list_resumable(max_age_days: int = 14) -> list[Candidate]:
    if not PROJECTS_DIR.is_dir():
        return []
    label_map = _labels_by_session_id()
    cutoff = datetime.now().timestamp() - (max_age_days * 86400)
    out: list[Candidate] = []
    seen: set[str] = set()
    for ws_dir in PROJECTS_DIR.iterdir():
        if not ws_dir.is_dir():
            continue
        for jsonl in ws_dir.glob("*.jsonl"):
            if "subagents" in jsonl.parts:
                continue
            sid = jsonl.stem
            if sid in seen:
                continue
            try:
                mtime = jsonl.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            seen.add(sid)
            cwd = _read_cwd(jsonl) or ""
            out.append(Candidate(
                session_id=sid,
                transcript=jsonl,
                cwd=cwd,
                mtime=mtime,
                first_prompt=_read_first_user_prompt(jsonl),
                permission_mode=_read_original_permission_mode(jsonl),
                labels=label_map.get(sid, []),
            ))
    out.sort(key=lambda c: -c.mtime)
    return out


def find_by_name(query: str, candidates: list[Candidate]) -> list[tuple[float, Candidate]]:
    """Fuzzy-match query against labels, session-id prefix, and first prompt."""
    q = query.lower().strip()
    q_tokens = set(re.findall(r"\w+", q))
    scored: list[tuple[float, Candidate]] = []
    now = datetime.now().timestamp()
    for c in candidates:
        score = 0.0
        if len(q) >= 8 and c.session_id.lower().startswith(q):
            score += 100
        for lbl in c.labels:
            lbl_l = lbl.lower()
            if lbl_l == q:
                score += 50
            elif q in lbl_l or lbl_l in q:
                score += 25
            score += 5 * len(q_tokens & set(re.findall(r"\w+", lbl_l)))
        if c.first_prompt:
            pt = set(re.findall(r"\w+", c.first_prompt.lower()))
            score += 1.5 * len(q_tokens & pt)
        if score > 0:
            # Mild recency tie-breaker, only among already-matching candidates.
            score += min(1.0, (c.mtime - (now - 14 * 86400)) / (14 * 86400))
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return scored


# ---------- liveness + permission verification (process = ground truth) ----------

def _alive_pid_for_session(sid: str) -> int | None:
    """Return the pid of a live session with this sessionId, or None."""
    if not SESSIONS_DIR.is_dir():
        return None
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("sessionId") == sid:
            pid = d.get("pid")
            return int(pid) if pid else None
    return None


def _await_liveness(sid: str, timeout_s: float) -> int | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pid = _alive_pid_for_session(sid)
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


# ---------- arg parsing ----------

def _slug(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", label).strip("-").lower()
    return s or "session"


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

    # Disambiguation: refuse to guess if the top two scores are within 20%.
    if len(matches) > 1 and matches[1][0] > matches[0][0] * 0.8:
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
    existing_pid = _alive_pid_for_session(cand.session_id)
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
    label = _slug(label)
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

    retries = 1
    for attempt in range(retries + 1):
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
            print(f"FAILED to resume {cand.session_id[:8]}.", file=sys.stderr)
            return 1

        print(out.splitlines()[0] if out else "(spawned)")

        if not opts["verify"]:
            return 0

        timeout = 25 if attempt == 0 else 40
        pid = _await_liveness(cand.session_id, timeout)
        if pid:
            actual = _verify_permission_mode_from_process(pid)
            verdict = "OK"
            note = ""
            if was_yolo and actual != "bypassPermissions":
                verdict = "WARN"
                note = f" (expected bypassPermissions, process shows {actual})"
            print(f"[{verdict}] alive (pid {pid}) -- verified perm from process: {actual}{note}")
            return 0 if verdict == "OK" else 1
        if attempt < retries:
            print("not alive yet, retrying once with a longer wait...")
            time.sleep(2)
            continue

    print(f"WARN: spawned but did not see a live pid for {cand.session_id[:8]} "
          f"within the timeout. It may still be loading -- check /window-list.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
