#!/usr/bin/env python3
"""window-kill.py — terminate spawned Claude sessions.

Usage:
  python window-kill.py <session-name>
  python window-kill.py --all              # kill every spawned session
  python window-kill.py --tag <name>       # kill every session in this tag group
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual  # noqa: E402
from window_tags import load_tags, prune_session, save_tags, sessions_with_tag, validate_tag  # noqa: E402


def find_pids_by_session_name(name: str | None) -> list[tuple[int, str]]:
    """Return list of (pid, command_line_snippet) for matching claude.exe processes."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
        "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    import json as _json
    try:
        data = _json.loads(result.stdout)
    except _json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    matches: list[tuple[int, str]] = []
    for entry in data:
        cmd = entry.get("CommandLine") or ""
        pid = entry.get("ProcessId")
        if "--remote-control" not in cmd:
            continue
        if name is None or name in cmd:
            matches.append((int(pid), cmd))
    return matches


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(
            "Usage: window-kill.py <session-name>  OR  --all  OR  --tag <name>",
            file=sys.stderr,
        )
        return 2

    # --tag <name>: kill every session carrying this tag.
    if argv[0] == "--tag":
        if len(argv) < 2:
            print("ERROR: --tag needs a tag name", file=sys.stderr)
            return 2
        tag = argv[1]
        ok, err = validate_tag(tag)
        if not ok:
            print(f"Bad --tag value: {err}", file=sys.stderr)
            return 2
        tagged = sessions_with_tag(tag)
        if not tagged:
            print(f"No sessions tagged '{tag}'. Nothing to kill.")
            return 0
        matches: list[tuple[int, str]] = []
        for actual in tagged:
            matches.extend(find_pids_by_session_name(actual))
        target = f"tag '{tag}' ({len(tagged)} tagged session(s))"
    elif argv[0] == "--all":
        target = "--all"
        matches = find_pids_by_session_name(None)
    else:
        target = argv[0]
        aliases = load_aliases()
        actual = resolve_to_actual(target, aliases)
        if actual != target:
            print(f"Resolved alias '{target}' -> '{actual}'")
        matches = find_pids_by_session_name(actual)

    if not matches:
        print(f"No matching live sessions found for: {target}")
        # For tag mode, prune any stale tag entries since the sessions are gone.
        if argv[0] == "--tag":
            from window_tags import remove_tag as _rm
            tags = load_tags()
            stale = sessions_with_tag(argv[1], tags)
            if stale:
                print(f"  (pruning {len(stale)} stale tag entries)")
                for actual in stale:
                    prune_session(actual, tags)
                save_tags(tags)
        return 1

    print(f"About to kill {len(matches)} session(s):")
    for pid, cmd in matches:
        snippet = cmd[:120] + ("..." if len(cmd) > 120 else "")
        print(f"  PID {pid}: {snippet}")

    killed = 0
    killed_actual_names: list[str] = []
    for pid, cmd in matches:
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
                check=True, timeout=5,
            )
            killed += 1
            # Extract the --remote-control <name> token so we can prune alias + tags.
            toks = cmd.split()
            for i, tok in enumerate(toks):
                if tok == "--remote-control" and i + 1 < len(toks):
                    killed_actual_names.append(toks[i + 1].strip('"'))
                    break
        except subprocess.SubprocessError as e:
            print(f"  FAILED to kill PID {pid}: {e}", file=sys.stderr)

    # Prune the alias and tag entries for whatever we just killed (dead session, dead metadata).
    if killed_actual_names:
        from window_aliases import save_aliases
        aliases = load_aliases()
        tags = load_tags()
        aliases_changed = False
        tags_changed = False
        for actual in killed_actual_names:
            if actual in aliases:
                del aliases[actual]
                aliases_changed = True
            if actual in tags:
                prune_session(actual, tags)
                tags_changed = True
        if aliases_changed:
            save_aliases(aliases)
        if tags_changed:
            save_tags(tags)

    print(f"Killed {killed}/{len(matches)}.")
    return 0 if killed == len(matches) else 1


if __name__ == "__main__":
    sys.exit(main())
