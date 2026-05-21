---
description: "Spawn N Claude worker sessions with the same first prompt, auto-tagged together."
argument-hint: "<N> \"<prompt>\" [--tag <name>] [--name-prefix <prefix>] [--mode <mode>] [--workspace <path>]"
---

!`python "$HOME/.claude/hooks/window-fanout.py" "$ARGUMENTS"`
