#!/usr/bin/env python3
"""window-rename.py — give a spawned session a friendlier local alias.

Usage:
  python window-rename.py <current-name> <new-name>

<current-name> can be either the actual session name (the value passed to
claude.exe via --remote-control) OR an existing alias.

IMPORTANT: this is a LOCAL alias only. It changes what /window-list shows
and what names /window-kill and /window-rename accept. It does NOT change
the name that Anthropic's remote-control registry holds for the session
— that's baked into the running process's command line at startup, and
claude.ai/code / the mobile app will keep showing the original name. To
fully "rename" a session as far as the web/mobile app is concerned you
have to kill it and respawn with --name <new-name>.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual, save_aliases, validate_label  # noqa: E402

LOG_PATH = Path.home() / ".claude" / "window-log.jsonl"


def lookup_launcher(actual_name: str) -> str | None:
    """Most recent /window-* mode used to spawn this session, if logged."""
    if not LOG_PATH.is_file():
        return None
    last_mode: str | None = None
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("session_name") == actual_name and e.get("mode"):
                    last_mode = e["mode"]
    except OSError:
        return None
    return last_mode


def running_session_names() -> set[str]:
    """Names currently registered as --remote-control on a live claude.exe."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
        "Select-Object -ExpandProperty CommandLine"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return set()
    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        if "--remote-control" not in line:
            continue
        toks = line.split()
        for i, tok in enumerate(toks):
            if tok == "--remote-control" and i + 1 < len(toks):
                names.add(toks[i + 1].strip('"'))
                break
    return names


def main() -> int:
    # Accept both "$ARGUMENTS" single-string form and two separate argv args.
    if len(sys.argv) == 2:
        parts = sys.argv[1].split()
        if len(parts) != 2:
            print(
                "Usage: window-rename.py <current-name> <new-name>",
                file=sys.stderr,
            )
            return 2
        current, new = parts[0], parts[1]
    elif len(sys.argv) == 3:
        current, new = sys.argv[1], sys.argv[2]
    else:
        print(
            "Usage: window-rename.py <current-name> <new-name>",
            file=sys.stderr,
        )
        return 2

    ok, err = validate_label(new)
    if not ok:
        print(f"Can't use '{new}' -- {err}")
        return 2

    aliases = load_aliases()
    actual = resolve_to_actual(current, aliases)

    alive = running_session_names()
    is_alive = actual in alive

    # Refuse to clobber an alias another session already uses.
    for other_actual, other_alias in aliases.items():
        if other_alias == new and other_actual != actual:
            print(f"Can't use '{new}' -- already taken by {other_actual}.")
            return 3

    old_display = aliases.get(actual, actual)
    aliases[actual] = new
    save_aliases(aliases)

    launcher = lookup_launcher(actual)
    launcher_cmd = f"/{launcher}" if launcher else "/<launcher>"

    print("Done." + ("" if is_alive else " (No live session matches this name -- renamed the label anyway.)"))
    print()
    print(f"Old name:  {old_display}")
    print(f"New name:  {new}")
    print()
    print("In your terminal, use the new name from now on.")
    print("On your phone, the session still shows the old name.")
    print()
    print("To rename it on your phone too, kill and relaunch:")
    print(f"  /window-kill {actual}")
    print(f"  {launcher_cmd} --name {new}")
    print("(You'll lose the conversation in that session.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
