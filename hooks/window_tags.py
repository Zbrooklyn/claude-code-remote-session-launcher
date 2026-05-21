#!/usr/bin/env python3
"""window_tags.py — shared helpers for the per-session tag map.

Tags are LOCAL ONLY (like aliases). They affect what /window-list shows
and filters on, and what /window-tag accepts. They do NOT travel with the
session anywhere outside this machine.

File format (~/.claude/window-tags.json):
    { "<actual_session_name>": ["tag1", "tag2", ...], ... }

Tags are stored against the actual session name (the --remote-control
value), not the alias. That way, renaming a session doesn't break its
tags, and killing a session prunes its tags cleanly.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

TAGS_PATH = Path.home() / ".claude" / "window-tags.json"

# Same rules as session labels: alphanumeric start, allowed chars are
# letters/digits/underscore/dot/dash, max 30 chars. Tags must NOT start
# with '-' so the leading-dash syntax `/window-tag <sess> -<tag>` can be
# used unambiguously to mean "remove this tag".
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,29}$")


def validate_tag(tag: str | None) -> tuple[bool, str]:
    """Return (ok, error_message). Empty/None tags are rejected."""
    if not tag:
        return (False, "tag is empty")
    if tag.startswith("-"):
        return (False, f"tag {tag!r} starts with '-' (reserved for the remove syntax)")
    if not _TAG_RE.match(tag):
        return (
            False,
            f"tag {tag!r} has invalid characters or is too long. "
            "Allowed: letters, digits, underscore, dot, dash. "
            "Must start with a letter/digit. Max 30 chars.",
        )
    return (True, "")


def load_tags() -> dict[str, list[str]]:
    if not TAGS_PATH.is_file():
        return {}
    try:
        data = json.loads(TAGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[str(k)] = sorted({str(t) for t in v if isinstance(t, str)})
    return out


def save_tags(tags: dict[str, list[str]]) -> None:
    # Prune empty lists; keep file tidy.
    cleaned = {k: sorted(set(v)) for k, v in tags.items() if v}
    TAGS_PATH.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")


def tags_for(actual: str, tags: dict[str, list[str]] | None = None) -> list[str]:
    if tags is None:
        tags = load_tags()
    return sorted(tags.get(actual, []))


def add_tag(actual: str, tag: str, tags: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    if tags is None:
        tags = load_tags()
    current = set(tags.get(actual, []))
    current.add(tag)
    tags[actual] = sorted(current)
    return tags


def remove_tag(actual: str, tag: str, tags: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    if tags is None:
        tags = load_tags()
    current = set(tags.get(actual, []))
    current.discard(tag)
    if current:
        tags[actual] = sorted(current)
    else:
        tags.pop(actual, None)
    return tags


def prune_session(actual: str, tags: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Drop all tags for a session (call after killing it)."""
    if tags is None:
        tags = load_tags()
    tags.pop(actual, None)
    return tags


def sessions_with_tag(tag: str, tags: dict[str, list[str]] | None = None) -> list[str]:
    if tags is None:
        tags = load_tags()
    return sorted([actual for actual, ts in tags.items() if tag in ts])
