#!/usr/bin/env python3
"""window-tag.py -- attach (or remove) tags on a spawned session.

Usage:
  python window-tag.py <session-name-or-alias> <tag>     # add tag
  python window-tag.py <session-name-or-alias> -<tag>    # remove tag
  python window-tag.py <session-name-or-alias>           # show tags for that session
  python window-tag.py --list                            # show all sessions with tags

Tags group sessions for filtering in /window-list (--tag <name>). They
are LOCAL ONLY -- they live in ~/.claude/window-tags.json and never reach
claude.ai/code or the mobile app.

A session can have any number of tags. Tags are stored against the actual
session name (the --remote-control value), so renaming a session via
/window-rename doesn't break its tags. Killing a session via /window-kill
prunes the session's tags automatically.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual, display_for  # noqa: E402
from window_tags import (  # noqa: E402
    load_tags, save_tags, tags_for, add_tag, remove_tag, validate_tag,
)


def cmd_list_all() -> int:
    tags = load_tags()
    if not tags:
        print("No tagged sessions.")
        return 0
    aliases = load_aliases()
    print("Tagged sessions:")
    print()
    for actual in sorted(tags):
        ts = tags[actual]
        alias = display_for(actual, aliases)
        display = f"{alias} (was {actual})" if alias else actual
        print(f"  {display}")
        print(f"    tags: {', '.join(ts)}")
    return 0


def cmd_show(actual: str, display: str) -> int:
    ts = tags_for(actual)
    if not ts:
        print(f"{display} has no tags.")
        print()
        print("To add one:")
        print(f"  /window-tag {display} <tag>")
        return 0
    print(f"{display}")
    print(f"  tags: {', '.join(ts)}")
    return 0


def cmd_add(actual: str, display: str, tag: str) -> int:
    ok, err = validate_tag(tag)
    if not ok:
        print(f"Can't use '{tag}' -- {err}")
        return 2
    current = tags_for(actual)
    if tag in current:
        print(f"{display} already has tag '{tag}'.")
        return 0
    tags = add_tag(actual, tag)
    save_tags(tags)
    new_tags = tags_for(actual, tags)
    print(f"Added '{tag}' to {display}.")
    print(f"  tags now: {', '.join(new_tags)}")
    return 0


def cmd_remove(actual: str, display: str, tag: str) -> int:
    ok, err = validate_tag(tag)  # validate the bare tag (not -tag)
    if not ok:
        print(f"Can't remove '{tag}' -- {err}")
        return 2
    current = tags_for(actual)
    if tag not in current:
        print(f"{display} doesn't have tag '{tag}'. Nothing to do.")
        if current:
            print(f"  current tags: {', '.join(current)}")
        return 0
    tags = remove_tag(actual, tag)
    save_tags(tags)
    remaining = tags_for(actual, tags)
    print(f"Removed '{tag}' from {display}.")
    if remaining:
        print(f"  tags now: {', '.join(remaining)}")
    else:
        print("  no tags left.")
    return 0


def main() -> int:
    # Accept both "$ARGUMENTS" single-string form and separate argv args.
    if len(sys.argv) == 2:
        parts = sys.argv[1].split()
    elif len(sys.argv) >= 3:
        parts = list(sys.argv[1:])
    else:
        print("Usage: window-tag.py <session-name-or-alias> [<tag>|-<tag>]", file=sys.stderr)
        print("       window-tag.py --list", file=sys.stderr)
        return 2

    if len(parts) == 1 and parts[0] == "--list":
        return cmd_list_all()

    if not parts:
        print("Usage: window-tag.py <session-name-or-alias> [<tag>|-<tag>]", file=sys.stderr)
        return 2

    target = parts[0]
    aliases = load_aliases()
    actual = resolve_to_actual(target, aliases)
    # If the user typed an alias, display the alias they typed; else show actual.
    display = target if (target != actual or display_for(actual, aliases) == target) else actual

    if len(parts) == 1:
        return cmd_show(actual, display)

    if len(parts) >= 2:
        op = parts[1]
        if op.startswith("-") and len(op) > 1:
            return cmd_remove(actual, display, op[1:])
        return cmd_add(actual, display, op)

    return 0


if __name__ == "__main__":
    sys.exit(main())
