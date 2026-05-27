#!/usr/bin/env python3
"""claude_env.py -- locate the `claude` CLI binary, portably.

Both spawn-window.py (which launches claude) and agents_state.py (which runs
`claude agents --json`) need the path to the claude executable. Hardcoding
~/.local/bin/claude.exe works on one machine and silently fails on everyone
else's -- the spawn just never starts. This resolves the binary the way a
stranger's machine actually has it:

  1. On PATH (shutil.which) -- the normal case for a proper install.
  2. Known per-platform install locations, as a fallback.

Result is cached so we don't re-probe on every call. Override with the
CLAUDE_BINARY environment variable if your install lives somewhere unusual.
"""
from __future__ import annotations
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


def claude_home() -> Path:
    """The Claude config dir (~/.claude). Honors the $CLAUDE_HOME environment
    variable so tests can point every hook at a temp dir instead of the real
    one. Resolved at call time, never cached, so a test can set it per-case."""
    override = os.environ.get("CLAUDE_HOME")
    return Path(override) if override else Path.home() / ".claude"


@lru_cache(maxsize=1)
def find_claude_binary() -> str | None:
    """Return an absolute path to the claude CLI, or None if it can't be found."""
    # 1. Explicit override.
    override = os.environ.get("CLAUDE_BINARY")
    if override and Path(override).exists():
        return override

    # 2. On PATH.
    for name in ("claude", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found

    # 3. Known install locations per platform.
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude.exe",
        home / ".local" / "bin" / "claude",
        home / "AppData" / "Local" / "Programs" / "claude" / "claude.exe",
        home / "AppData" / "Roaming" / "npm" / "claude.cmd",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def claude_binary_or_die() -> str:
    """Like find_claude_binary() but exits with a clear message if not found.
    For use at the top of a command that cannot proceed without claude."""
    b = find_claude_binary()
    if not b:
        print(
            "ERROR: could not find the `claude` CLI. Make sure Claude Code is "
            "installed and on your PATH, or set the CLAUDE_BINARY environment "
            "variable to its full path.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    return b
