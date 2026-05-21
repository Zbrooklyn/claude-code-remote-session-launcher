# Claude Code Remote Session Launcher

Claude Code Remote Session Launcher lets an active Claude Code workflow start additional Claude Code sessions in separate PowerShell terminals.

The first goal is simple: ask Claude Code to open a new Claude Code session in a remote-ready state so it can be accessed through Claude Code remote control. It supports configurable workspace paths, launch profiles, and autonomy presets without requiring the user to manually rebuild the command each time.

This project does not orchestrate or control child sessions yet. It is the launch layer for future multi-session Claude Code workflows.

---

## Status

Windows-only for now. Requires:
- Windows Terminal (`wt.exe`)
- Claude Code native build (`claude.exe`)
- PowerShell 7+ (`pwsh.exe`) — the installer uses features that don't work under Windows PowerShell 5.1. Install from https://github.com/PowerShell/PowerShell/releases if you don't have it. The runtime hooks only need Python 3, so day-to-day usage works in any shell.

## Install

1. Clone or download this repo.
2. Open PowerShell 7 (`pwsh`) in the repo root. The installer will refuse to run under Windows PowerShell 5.1.
3. Run `./install.ps1`. It copies the slash commands and hook scripts into `~/.claude/`.
4. In a Claude Code session, run `/window-setup` and answer 5 questions to write your config file.
5. Try `/window` from anywhere.

## What you get — 11 slash commands

`/window` — open a fresh Claude Code session in a new terminal window, standard permissions.

`/window-remote` — same, but with `--remote-control` attached so the session shows up in claude.ai/code and the official mobile app.

`/window-yolo` — fresh terminal session with `--dangerously-skip-permissions`. Use this for autonomous work in a sandboxed directory.

`/window-yolo-remote` — yolo plus remote-control. Autonomous worker you can reach from your phone.

`/daemon` — headless background session (new minimized terminal window), only reachable via Anthropic remote-control.

`/daemon-yolo` — headless plus skip-permissions. Autonomous, phone-only-reachable.

`/window-setup` — first-time setup wizard. Five multiple-choice questions, writes the config file.

`/window-list` — show recent spawns and which remote-controlled sessions are still alive.

`/window-kill <session-name>` — terminate a spawned session by its remote-control name. Use `--all` to kill every spawned session. Accepts either the original name or a local alias set via `/window-rename`.

`/window-rename <current-name> <new-name>` — give a spawned session a friendlier local alias. **LOCAL ONLY**: `/window-list`, `/window-kill`, and `/window-rename` use the new name; claude.ai/code and the mobile app keep showing the original. To get the new name on the web/app too, kill and respawn with `--name`.

`/window-attach <session-name-or-alias>` — bring a spawned session's Windows Terminal window to the foreground. Works on the actual `--remote-control` name or any local alias set via `/window-rename`. Brings the whole WT window forward; if multiple tabs are open, the right tab's title is `<label-or-session-name> | <workspace-name>` so you can spot it visually.

## Shared argument shape

All six spawn commands accept the same positional plus flag shape:

```
/<command> [workspace-path] ["first prompt"] [--worktree] [--name <label>]
```

- No args → opens in your configured default workspace, interactive.
- `<path>` → opens in that path (must be a Claude-Code-trusted directory, see Safety below).
- `<path> "<prompt>"` → opens in that path and types the quoted prompt as the first message.
- `--worktree` → adds `--worktree` to claude.exe to spawn in an isolated git worktree.
- `--name <label>` → session is named `<host-user>-<label>-<HHMMSS>` instead of the default `<host>-<mode>-<HHMMSS>`. Makes sessions easier to identify in `/window-list` and on claude.ai/code.

## Naming sessions

Two ways to give a session a friendly name:

1. **At launch time** — pass `--name <label>` to any spawn command. The label becomes part of the session's `--remote-control` name, so it shows up everywhere: terminal tools, claude.ai/code, mobile app. Example: `/window-yolo-remote --name bbw-staging` → session name `edward-bbw-staging-170842`.

2. **After launch** — `/window-rename old-name new-name`. This is a **local alias only**. It changes what `/window-list`, `/window-kill`, and `/window-rename` accept and display, but claude.ai/code and the mobile app continue to show the original name (the `--remote-control` value is fixed at process startup and can't be mutated externally).

If you want a renamed session to also show up under the new name on claude.ai/code, you have to kill the session and respawn it with `--name`. The rename command's output prints the exact `/window-kill` + relaunch commands to copy-paste.

Alias storage: `~/.claude/window-aliases.json`. Killing a session prunes its alias entry automatically.

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

- `~/.claude/commands/window.md` and 10 sibling slash-command files
- `~/.claude/hooks/spawn-window.py` — main launcher
- `~/.claude/hooks/window-list.py` — list spawned sessions
- `~/.claude/hooks/window-kill.py` — terminate spawned sessions
- `~/.claude/hooks/window-rename.py` — give sessions friendly local aliases
- `~/.claude/hooks/window-attach.py` — bring a session's terminal window to the foreground
- `~/.claude/hooks/window_aliases.py` — shared alias-map helpers

`install.ps1` preserves two files if they already exist in `~/.claude/`:
- `window-config.json` — your config (different per machine)
- `commands/window-setup.md` — the setup wizard prompt (often customized per environment, e.g. user name, channel labels)

If you want to refresh either from the repo, delete the file first, then re-run `install.ps1`.

## Uninstall

Delete the 11 files from `~/.claude/commands/` and the 6 files from `~/.claude/hooks/`. Optionally delete `~/.claude/window-config.json`, `~/.claude/window-log.jsonl`, and `~/.claude/window-aliases.json`.

## License

MIT.
