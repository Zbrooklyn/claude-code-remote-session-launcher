"""Factories for fake transcripts, session metadata, and spawn-log entries,
written into an isolated $CLAUDE_HOME for tests."""
from __future__ import annotations
import json
import time
from pathlib import Path


def write_transcript(home: Path, workspace_slug: str, sid: str, *,
                     cwd: str, first_prompt: str | None = None,
                     perm: str | None = None, age_days: float = 0.0) -> Path:
    """Create <home>/projects/<workspace_slug>/<sid>.jsonl with the records the
    catalog readers look for: a cwd carrier, an optional permission-mode event,
    and an optional first user prompt."""
    d = home / "projects" / workspace_slug
    d.mkdir(parents=True, exist_ok=True)
    lines: list[dict] = [{"type": "session-meta", "cwd": cwd}]
    if perm:
        lines.append({"type": "permission-mode", "permissionMode": perm})
    if first_prompt:
        lines.append({"type": "user", "message": {"content": [{"type": "text", "text": first_prompt}]}})
    p = d / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    if age_days:
        old = time.time() - age_days * 86400
        import os
        os.utime(p, (old, old))
    return p


def write_session(home: Path, pid: int, sid: str, *, cwd: str = "C:/x", name: str | None = None) -> Path:
    """Create <home>/sessions/<pid>.json (the live-session metadata file)."""
    d = home / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{pid}.json"
    obj = {"pid": pid, "sessionId": sid, "cwd": cwd}
    if name:
        obj["name"] = name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def write_log(home: Path, entries: list[dict]) -> Path:
    """Create <home>/window-log.jsonl from a list of entry dicts."""
    p = home / "window-log.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return p
