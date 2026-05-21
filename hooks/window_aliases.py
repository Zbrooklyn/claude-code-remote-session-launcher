#!/usr/bin/env python3
"""window-aliases.py — shared helpers for the local rename alias map.

Aliases are LOCAL ONLY. They affect what /window-list shows and what names
/window-kill / /window-rename accept. They do NOT change the
--remote-control name registered with Anthropic — that's baked into the
spawned process's command line and is what claude.ai/code displays. To
get the new name on the web/mobile app you have to kill and respawn.

File format (~/.claude/window-aliases.json):
    { "<actual_session_name>": "<current_alias>", ... }

actual_session_name is the value passed to claude.exe via --remote-control.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ALIASES_PATH = Path.home() / ".claude" / "window-aliases.json"

# Labels become part of --remote-control session names. They must be safe
# to embed in a shell argument, recognizable in logs, and not look like a
# CLI flag. Allow: letters, digits, underscore, dot, dash -- must START
# with an alphanumeric so leading dashes can't masquerade as flags.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,49}$")


def validate_label(label: str | None) -> tuple[bool, str]:
    """Return (ok, error_message). Empty/None labels are rejected."""
    if not label:
        return (False, "label is empty")
    if label.startswith("-"):
        return (False, f"label {label!r} starts with '-' (looks like a CLI flag)")
    if not _LABEL_RE.match(label):
        return (
            False,
            f"label {label!r} has invalid characters or is too long. "
            "Allowed: letters, digits, underscore, dot, dash. "
            "Must start with a letter/digit. Max 50 chars.",
        )
    return (True, "")


def load_aliases() -> dict[str, str]:
    if not ALIASES_PATH.is_file():
        return {}
    try:
        data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_aliases(aliases: dict[str, str]) -> None:
    ALIASES_PATH.write_text(json.dumps(aliases, indent=2), encoding="utf-8")


def resolve_to_actual(name: str, aliases: dict[str, str] | None = None) -> str:
    """Given a name the user typed, return the actual session_name.

    If `name` is already an actual session name (a key in the map, or any
    name not present as a value), return it unchanged. If `name` is a
    current alias (a value in the map), return the corresponding key.
    """
    if aliases is None:
        aliases = load_aliases()
    if name in aliases:  # already actual
        return name
    for actual, alias in aliases.items():
        if alias == name:
            return actual
    return name  # unknown — caller will decide if that's a problem


def display_for(actual: str, aliases: dict[str, str] | None = None) -> str | None:
    """Return the current alias for an actual session name, or None."""
    if aliases is None:
        aliases = load_aliases()
    return aliases.get(actual)
