---
description: "Resume a CURATED SET of past Claude sessions in one shot (your 'resume all my conversations' set). Preview by default; add --go to launch. Filter with --theme/--slug/--state. Reuses /window-resume per session (original cwd, original perm mode, remote, dup-guarded)."
argument-hint: "[--go] [--all | --theme T | --slug S | --state ST]"
---

!`python "$HOME/.claude/hooks/window-resume-all.py" "$ARGUMENTS"`
