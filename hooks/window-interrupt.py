#!/usr/bin/env python3
"""Compatibility wrapper: /window-interrupt delegates to agentctl interrupt."""
from __future__ import annotations
import sys
from agentctl import main

if __name__ == "__main__":
    sys.exit(main(["interrupt", *sys.argv[1:], "--json"]))
