#!/usr/bin/env python3
"""window_sessions.py -- shared session-catalog + fuzzy-match helpers.

Single source of truth for "what past sessions exist and which transcript is
which." Both window-resume.py (which RESUMES a match) and window-find.py (which
LISTS matches for the agent to choose) import from here, so their matching can
never drift apart.

Conventions match the other shared helpers (window_aliases.py, window_tags.py):
underscore-named module, imported via `sys.path.insert(0, hooks_dir)`.

Paths resolve at call time via claude_env.claude_home(), which honors the
$CLAUDE_HOME env var -- so the test suite can isolate against a temp dir and
never touch the real ~/.claude.

What lives here:
  - Candidate           -- one resumable session + the metadata resume/find need
  - list_resumable()    -- walk <claude_home>/projects/*/*.jsonl into Candidates
  - find_by_name()      -- fuzzy rank Candidates against a query
  - alive_session_ids() -- set of sessionIds with a live process (ground truth)
  - alive_pid_for_session() / transcript readers / slug helper

What deliberately does NOT live here: anything that spawns or kills. Those are
actions, and they belong to the command hooks, not this read-only catalog layer.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_env import claude_home  # noqa: E402


def projects_dir() -> Path:
    return claude_home() / "projects"


def sessions_dir() -> Path:
    return claude_home() / "sessions"


def log_path() -> Path:
    return claude_home() / "window-log.jsonl"


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

def read_field_early(jsonl: Path, key: str, max_lines: int = 80) -> str | None:
    """First value of a top-level `key` in the transcript head."""
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


def read_cwd(jsonl: Path) -> str | None:
    """Authoritative workspace: the transcript's own `cwd` field.

    Never decode the project-dir slug instead -- that decode is lossy (every
    non-alphanumeric char becomes '-', so it can't be reversed), and resuming
    in the wrong directory makes the session die on launch.
    """
    cwd = read_field_early(jsonl, "cwd")
    return cwd.replace("\\", "/") if cwd else None


def read_original_permission_mode(jsonl: Path, max_lines: int = 200) -> str | None:
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


def read_first_user_prompt(jsonl: Path, max_lines: int = 80) -> str | None:
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
                if text.startswith(("<", "Caveat:", "[Request", "===", "Launched")):
                    continue
                return text[:500]
    except OSError:
        return None
    return None


# ---------- spawn-label correlation ----------

def labels_by_session_id() -> dict[str, list[str]]:
    """Map session_id -> [labels] from the spawn log. Best-effort: fresh spawns
    log a session_name but not the claude session_id, so the fuzzy matcher also
    searches first prompts. Resume + auto-capture entries DO carry session_id."""
    out: dict[str, list[str]] = {}
    lp = log_path()
    if not lp.is_file():
        return out
    try:
        with lp.open("r", encoding="utf-8") as f:
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
    """Walk <claude_home>/projects/*/*.jsonl into Candidates, newest first."""
    pd = projects_dir()
    if not pd.is_dir():
        return []
    label_map = labels_by_session_id()
    cutoff = datetime.now().timestamp() - (max_age_days * 86400)
    out: list[Candidate] = []
    seen: set[str] = set()
    for ws_dir in pd.iterdir():
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
            out.append(Candidate(
                session_id=sid,
                transcript=jsonl,
                cwd=read_cwd(jsonl) or "",
                mtime=mtime,
                first_prompt=read_first_user_prompt(jsonl),
                permission_mode=read_original_permission_mode(jsonl),
                labels=label_map.get(sid, []),
            ))
    out.sort(key=lambda c: -c.mtime)
    return out


def find_by_name(query: str, candidates: list[Candidate]) -> list[tuple[float, Candidate]]:
    """Fuzzy-rank query against labels, session-id prefix, and first prompt.
    Returns (score, candidate) sorted high-to-low; empty if nothing matches."""
    q = query.lower().strip()
    q_tokens = set(re.findall(r"\w+", q))
    now = datetime.now().timestamp()
    scored: list[tuple[float, Candidate]] = []
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
            score += min(1.0, (c.mtime - (now - 14 * 86400)) / (14 * 86400))
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return scored


def is_ambiguous(matches: list[tuple[float, Candidate]]) -> bool:
    """True if the top two matches are within 20% -- too close to auto-pick."""
    return len(matches) > 1 and matches[1][0] > matches[0][0] * 0.8


# ---------- liveness (ground truth: process table, not just metadata files) ----------

def running_claude_pids() -> set[int]:
    """Set of pids for claude processes ACTUALLY running right now (process
    table), not metadata files. This is what makes liveness ground-truth:
    <claude_home>/sessions/*.json files linger after a hard kill or crash, so
    trusting them alone reports dead sessions as alive."""
    if sys.platform == "win32":
        ps = "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | Select-Object -ExpandProperty ProcessId"
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                               capture_output=True, text=True, timeout=10)
        except (subprocess.SubprocessError, FileNotFoundError):
            return set()
        out: set[int] = set()
        for tok in (r.stdout or "").split():
            try:
                out.add(int(tok))
            except ValueError:
                continue
        return out
    # POSIX
    try:
        r = subprocess.run(["ps", "-eo", "pid,comm,args"], capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    out = set()
    for line in r.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) >= 2 and "claude" in line.lower():
            try:
                out.add(int(parts[0]))
            except ValueError:
                continue
    return out


def _sessions_meta() -> list[dict]:
    out: list[dict] = []
    sd = sessions_dir()
    if not sd.is_dir():
        return out
    for f in sd.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def alive_session_ids() -> set[str]:
    """Set of sessionIds whose process is ACTUALLY running. A metadata file is
    only counted if its pid is in the live process table -- stale files left by
    a crashed/killed session are correctly treated as dead."""
    running = running_claude_pids()
    out: set[str] = set()
    for d in _sessions_meta():
        sid, pid = d.get("sessionId"), d.get("pid")
        if sid and pid and int(pid) in running:
            out.add(sid)
    return out


def alive_pid_for_session(sid: str) -> int | None:
    """Pid of a session with this sessionId that is ACTUALLY running, or None.
    Stale metadata for a dead pid is ignored."""
    running = running_claude_pids()
    for d in _sessions_meta():
        if d.get("sessionId") == sid:
            pid = d.get("pid")
            if pid and int(pid) in running:
                return int(pid)
    return None


def slug(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", label).strip("-").lower()
    return s or "session"
