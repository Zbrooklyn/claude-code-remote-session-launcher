#!/usr/bin/env python3
"""Compatibility wrapper: /window-send delegates to the shared agentctl CLI."""
from __future__ import annotations
import sys
from agentctl import main

if __name__ == "__main__":
    # Slash commands deliver arguments as one quoted string on some clients.
    import shlex
    args = sys.argv[1:]
    if len(args) == 1:
        args = shlex.split(args[0], posix=False)
    sys.exit(main(["send", *args, "--enter", "--json"]))
