#!/usr/bin/env python3
"""window-context.py -- show recent turns from a session's transcript.

Usage:
  python window-context.py <session-name-or-alias> [--turns N] [--full]

Looks up the session's transcript file at
~/.claude/projects/<sanitized-cwd>/<sessionId>.jsonl and prints the
last N user/assistant turns. Default --turns is 3.

--full prints the entire text content of each turn (no truncation).
Without --full, each message is truncated to ~400 chars for skimming.

This is the "what did the worker actually produce?" half of the
orchestration loop -- pairs with /window-status (is it done?) and
/window-wait (block until done).

Works on dead sessions too -- the transcript file persists after the
process exits. We resolve cwd from the agents listing for live
sessions, and fall back to scanning ~/.claude/projects/ for a
matching transcript filename when the session is no longer live.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual  # noqa: E402
from agents_state import by_remote_control_name  # noqa: E402

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def cwd_to_project_dir(cwd: str) -> str:
    """Mirror Claude Code's cwd -> project-dir sanitizer."""
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def find_transcript(session_id: str, cwd: str | None) -> Path | None:
    """Locate the JSONL transcript for a given sessionId.

    Prefer the cwd-derived path when known (fast). Fall back to a
    scan of ~/.claude/projects/**/<sessionId>.jsonl for dead sessions
    where we don't know the cwd anymore.
    """
    if cwd:
        candidate = PROJECTS_DIR / cwd_to_project_dir(cwd) / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    # Fallback: scan all project dirs.
    if PROJECTS_DIR.is_dir():
        for p in PROJECTS_DIR.rglob(f"{session_id}.jsonl"):
            if "subagents" in p.parts:
                continue
            return p
    return None


def extract_text(message: dict) -> str:
    """Return the human-readable text body of a user or assistant message."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            t = block.get("type")
            if t == "text":
                parts.append(str(block.get("text", "")))
            elif t == "tool_use":
                name = block.get("name", "?")
                parts.append(f"[tool_use: {name}]")
            elif t == "tool_result":
                # Tool results are usually attached to user messages.
                tc = block.get("content")
                if isinstance(tc, str):
                    parts.append(f"[tool_result: {tc[:80]}...]" if len(tc) > 80 else f"[tool_result: {tc}]")
                else:
                    parts.append("[tool_result: ...]")
            elif t == "thinking":
                # Skip thinking; it's noisy. Show a marker so the reader knows
                # the assistant thought before responding.
                parts.append("[thinking...]")
        return "\n".join(p for p in parts if p)
    return ""


def load_turns(transcript: Path) -> list[dict]:
    """Read the JSONL and return user/assistant turns in order."""
    turns: list[dict] = []
    try:
        with transcript.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = o.get("type")
                if t not in ("user", "assistant"):
                    continue
                msg = o.get("message")
                if not isinstance(msg, dict):
                    continue
                turns.append({
                    "role": t,
                    "ts": o.get("timestamp", ""),
                    "text": extract_text(msg),
                })
    except OSError:
        return []
    return turns


def parse_int_flag(argv: list[str], flag: str, default: int) -> int:
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    for i, tok in enumerate(flat):
        if tok == flag and i + 1 < len(flat):
            try:
                return int(flat[i + 1])
            except ValueError:
                print(f"ERROR: {flag} needs an integer, got {flat[i + 1]!r}", file=sys.stderr)
                sys.exit(2)
    return default


def parse_positional(argv: list[str]) -> list[str]:
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    positional: list[str] = []
    skip_next = False
    for tok in flat:
        if skip_next:
            skip_next = False
            continue
        if tok in ("--turns",):
            skip_next = True
            continue
        if tok.startswith("--"):
            continue
        positional.append(tok)
    return positional


def truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + f"... [truncated, {len(s) - limit} more chars]"


def session_id_from_log(actual: str) -> tuple[str | None, str | None]:
    """For dead sessions, dig the most recent sessionId + cwd out of the spawn log."""
    log_path = Path.home() / ".claude" / "window-log.jsonl"
    if not log_path.is_file():
        return (None, None)
    last_cwd: str | None = None
    try:
        with log_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("session_name") == actual:
                    last_cwd = o.get("workspace")
    except OSError:
        pass
    # The spawn log doesn't store sessionId, so for dead sessions we can
    # only narrow to a directory. Caller will scan it for any transcript
    # the session might have produced.
    return (None, last_cwd)


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: window-context.py <session-name-or-alias> [--turns N] [--full]", file=sys.stderr)
        return 2

    turns_n = parse_int_flag(argv, "--turns", 3)
    if turns_n < 1:
        print("ERROR: --turns must be >= 1", file=sys.stderr)
        return 2
    full = any("--full" in a.split() for a in argv)
    positional = parse_positional(argv)
    if not positional:
        print("ERROR: provide a session name or alias.", file=sys.stderr)
        return 2

    target = positional[0]
    aliases = load_aliases()
    actual = resolve_to_actual(target, aliases)
    if actual != target:
        print(f"Resolved alias '{target}' -> '{actual}'")

    live = by_remote_control_name()
    agent = live.get(actual)
    session_id: str | None = None
    cwd: str | None = None
    is_alive = False
    if agent:
        is_alive = True
        session_id = agent.get("sessionId")
        cwd = agent.get("cwd")
    else:
        # Dead session — recover cwd from log if we can; sessionId we'll find by scan.
        _, cwd = session_id_from_log(actual)

    transcript: Path | None = None
    if session_id:
        transcript = find_transcript(session_id, cwd)

    if not transcript and not is_alive:
        # Last-ditch: scan known project dir for any transcript file.
        # We can't tie it to this specific session without sessionId.
        print(f"Session '{actual}' is dead and we don't have its sessionId.")
        print("Transcripts are keyed by sessionId, which is only knowable while the")
        print("process is alive. Try /window-list to spot any live sibling sessions.")
        return 1

    if not transcript:
        print(f"Couldn't locate a transcript file for '{actual}'.")
        print(f"  sessionId={session_id}")
        print(f"  cwd={cwd}")
        return 1

    turns = load_turns(transcript)
    if not turns:
        print(f"No user/assistant turns found in transcript yet.")
        print(f"  {transcript}")
        return 0

    recent = turns[-turns_n * 2:]  # rough: try to capture pairs
    # Actually just take the last turns_n turns regardless of role.
    recent = turns[-turns_n:]

    header_status = "[ALIVE]" if is_alive else "[dead]"
    print(f"{header_status}  {actual}")
    print(f"  sessionId: {session_id or '?'}")
    print(f"  transcript: {transcript}")
    print(f"  showing last {len(recent)} turn(s) of {len(turns)} total")
    print()
    print("-" * 70)
    limit = 99999 if full else 400
    for t in recent:
        ts = t.get("ts", "")[:19]  # YYYY-MM-DDTHH:MM:SS
        role = t["role"].upper()
        text = t["text"] or "(no text content)"
        print(f"[{ts}] {role}")
        print(truncate(text, limit))
        print("-" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
