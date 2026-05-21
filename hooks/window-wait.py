#!/usr/bin/env python3
"""window-wait.py -- block until a spawned session (or a tag group) goes idle.

Usage:
  python window-wait.py <session-name-or-alias> [--timeout N] [--poll N]
  python window-wait.py --tag <name>           [--timeout N] [--poll N]

Defaults: --timeout 300 (5 min), --poll 2 (seconds).

Exit codes:
  0  target(s) became idle within the timeout
  1  timed out while target was still busy
  2  bad input (unknown session, invalid args)

This is the orchestration primitive for "spawn worker(s), wait for them
to finish, then act on the result." Combines with /window-tag for the
fan-out pattern: tag N workers, then /window-wait --tag <name>.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual  # noqa: E402
from window_tags import sessions_with_tag, load_tags, validate_tag  # noqa: E402
from agents_state import by_remote_control_name, format_age  # noqa: E402


DEFAULT_TIMEOUT_S = 300
DEFAULT_POLL_S = 2


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


def parse_value_flag(argv: list[str], flag: str) -> str | None:
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    for i, tok in enumerate(flat):
        if tok == flag and i + 1 < len(flat):
            return flat[i + 1]
    return None


def parse_positional(argv: list[str], known_flags: set[str]) -> list[str]:
    """Pull positional tokens out of argv, skipping known --flag VALUE pairs."""
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    positional: list[str] = []
    i = 0
    while i < len(flat):
        tok = flat[i]
        if tok in known_flags:
            i += 2  # consume flag + value
            continue
        if tok.startswith("--"):
            i += 1
            continue
        positional.append(tok)
        i += 1
    return positional


def wait_for(targets: set[str], timeout_s: int, poll_s: int, label: str) -> int:
    """Poll until all targets are not-busy. Returns exit code."""
    start = time.monotonic()
    deadline = start + timeout_s
    last_busy: set[str] = set(targets)

    print(f"Waiting on {label} (timeout={timeout_s}s, poll={poll_s}s)...")
    print()

    while True:
        live = by_remote_control_name()
        # Sessions not present in `live` are dead. A dead session counts as
        # "done" -- it can't be busy anymore.
        still_busy = {
            name for name in targets
            if name in live and live[name].get("status") == "busy"
        }

        if still_busy != last_busy:
            elapsed = int(time.monotonic() - start)
            if still_busy:
                names = ", ".join(sorted(still_busy))
                print(f"  [{elapsed:>4}s] still busy: {names}")
            last_busy = still_busy

        if not still_busy:
            elapsed = int(time.monotonic() - start)
            print()
            # Report final state of each target.
            for name in sorted(targets):
                a = live.get(name)
                if not a:
                    print(f"  {name} -- dead (process gone)")
                else:
                    age = format_age(a.get("startedAt"))
                    print(f"  {name} -- [{a.get('status')}]  age={age}")
            print()
            print(f"Done after {elapsed}s.")
            return 0

        if time.monotonic() >= deadline:
            elapsed = int(time.monotonic() - start)
            print()
            print(f"TIMEOUT after {elapsed}s. Still busy: {', '.join(sorted(still_busy))}")
            return 1

        time.sleep(poll_s)


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print("Usage: window-wait.py <session-name-or-alias> [--timeout N] [--poll N]", file=sys.stderr)
        print("       window-wait.py --tag <name>           [--timeout N] [--poll N]", file=sys.stderr)
        return 2

    known_flags = {"--timeout", "--poll", "--tag"}
    timeout_s = parse_int_flag(argv, "--timeout", DEFAULT_TIMEOUT_S)
    poll_s = parse_int_flag(argv, "--poll", DEFAULT_POLL_S)
    if timeout_s < 1 or poll_s < 1:
        print("ERROR: --timeout and --poll must be >= 1", file=sys.stderr)
        return 2

    tag = parse_value_flag(argv, "--tag")
    aliases = load_aliases()

    if tag:
        ok, err = validate_tag(tag)
        if not ok:
            print(f"Bad --tag value: {err}", file=sys.stderr)
            return 2
        tags = load_tags()
        targets = set(sessions_with_tag(tag, tags))
        if not targets:
            print(f"No sessions tagged '{tag}'. Nothing to wait on.")
            return 0
        label = f"tag '{tag}' ({len(targets)} session(s))"
    else:
        positional = parse_positional(argv, known_flags)
        if not positional:
            print("ERROR: provide a session name/alias, or --tag <name>.", file=sys.stderr)
            return 2
        target_in = positional[0]
        actual = resolve_to_actual(target_in, aliases)
        if actual != target_in:
            print(f"Resolved alias '{target_in}' -> '{actual}'")
        live = by_remote_control_name()
        if actual not in live:
            print(f"No live session named '{actual}'. Run /window-list to see what's running.")
            return 2
        targets = {actual}
        label = actual

    return wait_for(targets, timeout_s, poll_s, label)


if __name__ == "__main__":
    sys.exit(main())
