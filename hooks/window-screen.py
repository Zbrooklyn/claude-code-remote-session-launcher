#!/usr/bin/env python3
"""Compatibility wrapper: /window-screen delegates to agentctl read."""
from __future__ import annotations
import sys
from agentctl import main

if __name__ == "__main__":
    sys.exit(main(["read", *sys.argv[1:], "--json"]))
