#!/usr/bin/env python3
"""window-fanout.py -- spawn N copies of a worker session with the same first prompt.

Usage:
  python window-fanout.py <N> "<first prompt>" [--tag <name>] [--name-prefix <prefix>]
                                                [--mode <window-mode>] [--workspace <path>]

Examples:
  python window-fanout.py 3 "audit this repo for security issues" --tag review
  python window-fanout.py 5 "summarize this PR" --tag pr-871 --mode window-yolo-remote

Each spawned session is named "<prefix>-<i>" (default prefix: 'fanout').
All sessions get tagged with --tag <name> so you can /window-wait and
/window-kill the group as a unit.

After spawning, prints the exact /window-wait command to monitor the
group and the /window-context commands to read each worker's output.

Defaults:
  --mode          window-yolo-remote   (autonomous + remote-controllable)
  --name-prefix   fanout
  --tag           (auto-generated: 'fanout-<HHMMSS>')
  --workspace     (uses spawn-window's default-workspace from config)
"""
from __future__ import annotations
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import validate_label  # noqa: E402
from window_tags import validate_tag, save_tags, add_tag, load_tags  # noqa: E402

SPAWN_PATH = Path(__file__).parent / "spawn-window.py"

VALID_MODES = {
    "window-yolo-remote",
    "window-remote",
    "daemon",
    "daemon-yolo",
}


def parse_value_flag(argv: list[str], flag: str) -> str | None:
    flat: list[str] = []
    for a in argv:
        flat.extend(a.split())
    for i, tok in enumerate(flat):
        if tok == flag and i + 1 < len(flat):
            return flat[i + 1]
    return None


def parse_positional(argv: list[str], known_flags: set[str]) -> list[str]:
    """Pull positional tokens, skipping known --flag VALUE pairs. Preserves
    quoted positionals as single tokens."""
    # We want to preserve the prompt as a single positional even if it
    # contains spaces. shell handed us argv with shell-respected quoting
    # already, so single-token splits are wrong. Walk argv directly.
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in known_flags:
            i += 2
            continue
        if tok.startswith("--"):
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def spawn_one(mode: str, prompt: str, label: str, workspace: str | None) -> tuple[str | None, str]:
    """Invoke spawn-window.py once. Returns (actual_session_name, raw_output)."""
    cmd = ["python", str(SPAWN_PATH), mode]
    # Build the single-string argument that spawn-window.py expects.
    arg_parts: list[str] = []
    if workspace:
        # Quote in case it has spaces.
        arg_parts.append(f'"{workspace}"' if " " in workspace else workspace)
    # Always quote the prompt (it almost always has spaces).
    arg_parts.append(f'"{prompt}"')
    arg_parts.append("--name")
    arg_parts.append(label)
    cmd.append(" ".join(arg_parts))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return (None, f"spawn failed: {e}")
    output = (result.stdout or "") + (result.stderr or "")
    # spawn-window prints "Remote session: <name>" on success
    sess_name: str | None = None
    for line in output.splitlines():
        if "Remote session:" in line:
            sess_name = line.split("Remote session:", 1)[1].strip()
            break
    return (sess_name, output.strip())


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(
            "Usage: window-fanout.py <N> \"<first prompt>\" "
            "[--tag <name>] [--name-prefix <prefix>] [--mode <mode>] [--workspace <path>]",
            file=sys.stderr,
        )
        return 2

    known_flags = {"--tag", "--name-prefix", "--mode", "--workspace"}
    tag = parse_value_flag(argv, "--tag")
    name_prefix = parse_value_flag(argv, "--name-prefix") or "fanout"
    mode = parse_value_flag(argv, "--mode") or "window-yolo-remote"
    workspace = parse_value_flag(argv, "--workspace")

    if mode not in VALID_MODES:
        print(
            f"ERROR: --mode {mode!r} is not valid for fan-out.\n"
            f"Valid modes (must support --remote-control): {sorted(VALID_MODES)}",
            file=sys.stderr,
        )
        return 2

    ok, err = validate_label(name_prefix)
    if not ok:
        print(f"ERROR: --name-prefix invalid -- {err}", file=sys.stderr)
        return 2

    if tag is None:
        # Auto-generate a tag scoped to this fan-out batch so the user can
        # always rejoin the group later.
        tag = f"{name_prefix}-{datetime.now().strftime('%H%M%S')}"
    ok, err = validate_tag(tag)
    if not ok:
        print(f"ERROR: --tag invalid -- {err}", file=sys.stderr)
        return 2

    positional = parse_positional(argv, known_flags)
    if len(positional) < 2:
        print(
            "ERROR: provide N and the first prompt.\n"
            "Example: window-fanout.py 3 \"audit this repo\" --tag review",
            file=sys.stderr,
        )
        return 2
    try:
        n = int(positional[0])
    except ValueError:
        print(f"ERROR: N must be an integer, got {positional[0]!r}", file=sys.stderr)
        return 2
    if n < 1 or n > 20:
        print(f"ERROR: N must be between 1 and 20 (got {n}). Fan-out is for groups, not raids.", file=sys.stderr)
        return 2

    prompt = " ".join(positional[1:])

    print(f"Fanning out {n} workers (mode={mode}, tag={tag}, prefix={name_prefix})...")
    print()

    spawned: list[tuple[int, str | None, str]] = []
    for i in range(1, n + 1):
        label = f"{name_prefix}-{i}"
        # Validate the per-worker label too (prefix-1 etc).
        ok, err = validate_label(label)
        if not ok:
            print(f"  worker {i}: skipped (label {label!r} invalid: {err})")
            continue
        sess_name, raw = spawn_one(mode, prompt, label, workspace)
        spawned.append((i, sess_name, raw))
        if sess_name:
            print(f"  worker {i}: {sess_name}")
        else:
            print(f"  worker {i}: SPAWN FAILED")
            print(f"    {raw}")
        # Small stagger so timestamps in session names differ.
        if i < n:
            time.sleep(1.1)

    # Tag every spawned session.
    tags = load_tags()
    tagged = 0
    for _, sess_name, _ in spawned:
        if sess_name:
            tags = add_tag(sess_name, tag, tags)
            tagged += 1
    if tagged:
        save_tags(tags)

    successes = [s for _, s, _ in spawned if s]
    print()
    print(f"Spawned {len(successes)}/{n}. Tagged {tagged} with '{tag}'.")
    if not successes:
        return 1
    print()
    print("To watch the group:")
    print(f"  /window-list --tag {tag}")
    print(f"  /window-wait --tag {tag}")
    print()
    print("After they finish, read each one's output:")
    for s in successes:
        print(f"  /window-context {s}")
    print()
    print("To clean up the whole group:")
    print(f"  /window-kill --tag {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
