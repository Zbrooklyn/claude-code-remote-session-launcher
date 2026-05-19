# Claude Code Remote Session Launcher

Claude Code Remote Session Launcher lets an active Claude Code workflow start additional Claude Code sessions in separate PowerShell terminals.

The first goal is simple: ask Claude Code to open a new Claude Code session in a remote-ready state so it can be accessed through Claude Code remote control. It supports configurable workspace paths, launch profiles, and autonomy presets without requiring the user to manually rebuild the command each time.

This project does not orchestrate or control child sessions yet. It is the launch layer for future multi-session Claude Code workflows.

---

## Status

Windows-only for now. Requires Windows Terminal (`wt.exe`) and the Claude Code native build (`claude.exe`).

## Install

1. Clone or download this repo.
2. Open PowerShell in the repo root.
3. Run `./install.ps1`. It copies the slash commands and hook scripts into `~/.claude/`.
4. In a Claude Code session, run `/window-setup` and answer 5 questions to write your config file.
5. Try `/window` from anywhere.

## What you get — 9 slash commands

`/window` — open a fresh Claude Code session in a new terminal window, standard permissions.

`/window-remote` — same, but with `--remote-control` attached so the session shows up in claude.ai/code and the official mobile app.

`/window-yolo` — fresh terminal session with `--dangerously-skip-permissions`. Use this for autonomous work in a sandboxed directory.

`/window-yolo-remote` — yolo plus remote-control. Autonomous worker you can reach from your phone.

`/daemon` — headless background session (new minimized terminal window), only reachable via Anthropic remote-control.

`/daemon-yolo` — headless plus skip-permissions. Autonomous, phone-only-reachable.

`/window-setup` — first-time setup wizard. Five multiple-choice questions, writes the config file.

`/window-list` — show recent spawns and which remote-controlled sessions are still alive.

`/window-kill <session-name>` — terminate a spawned session by its remote-control name. Use `--all` to kill every spawned session.

## Shared argument shape

All six spawn commands accept the same positional plus flag shape:

```
/<command> [workspace-path] ["first prompt"] [--worktree]
```

- No args → opens in your configured default workspace, interactive.
- `<path>` → opens in that path (must be a Claude-Code-trusted directory, see Safety below).
- `<path> "<prompt>"` → opens in that path and types the quoted prompt as the first message.
- `--worktree` → adds `--worktree` to claude.exe to spawn in an isolated git worktree.

## Safety model

The launcher refuses to spawn into directories that aren't already trusted by Claude Code. This is intentional — a remote-spawn into an untrusted directory would just sit waiting for someone to click the trust dialog on the laptop, which defeats the point.

Three layers:

1. **Default workspace** — your `/window-setup` answer. Always works.
2. **Trusted directories** — anything you've opened in Claude Code locally at least once. The launcher reads Claude's trust list at `~/.claude.json` and allows those.
3. **Extra allow-list** — optional. Edit `~/.claude/window-config.json` and add directories you've vetted but haven't opened locally yet.

If you try to spawn into an untrusted path, you get a clear error with the fix.

## Config file

Lives at `~/.claude/window-config.json`. Written by `/window-setup`. Schema:

```json
{
  "default_workspace": "C:/path/to/your/main/workspace",
  "default_yolo": false,
  "default_remote": false,
  "extra_allow_list": []
}
```

Edit by hand whenever you want — the launcher re-reads it every spawn.

## Spawn log

Every successful spawn appends a JSONL line to `~/.claude/window-log.jsonl`. `/window-list` reads this and cross-references running processes to show which sessions are alive.

## Files installed by `install.ps1`

- `~/.claude/commands/window.md` and 8 sibling slash-command files
- `~/.claude/hooks/spawn-window.py` — main launcher
- `~/.claude/hooks/window-list.py` — list spawned sessions
- `~/.claude/hooks/window-kill.py` — terminate spawned sessions

`install.ps1` will not overwrite an existing `window-config.json` if you have one.

## Uninstall

Delete the 9 files from `~/.claude/commands/` and the 3 files from `~/.claude/hooks/`. Optionally delete `~/.claude/window-config.json` and `~/.claude/window-log.jsonl`.

## License

MIT.
