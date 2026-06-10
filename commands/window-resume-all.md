---
description: "Resume a CURATED SET of past Claude sessions in one shot (your 'resume all my conversations' set), each GROUPED into a Windows Terminal window named for its category (catalog parent_theme) -- same-category sessions become tabs in one window; window count is emergent from the data. Preview by default (prints the factual session->category->window map); add --go to launch. Filter with --theme/--slug/--state. Reuses /window-resume per session (original cwd, original perm mode, remote, dup-guarded)."
argument-hint: "[--go] [--all | --theme T | --slug S | --state ST]"
---

!`python "$HOME/.claude/hooks/window-resume-all.py" "$ARGUMENTS"`
