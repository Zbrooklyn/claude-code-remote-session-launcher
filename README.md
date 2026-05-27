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

## What you get — 17 slash commands

`/window` — open a fresh Claude Code session in a new terminal window, standard permissions.

`/window-remote` — same, but with `--remote-control` attached so the session shows up in claude.ai/code and the official mobile app.

`/window-yolo` — fresh terminal session with `--dangerously-skip-permissions`. Use this for autonomous work in a sandboxed directory.

`/window-yolo-remote` — yolo plus remote-control. Autonomous worker you can reach from your phone.

`/daemon` — headless background session (new minimized terminal window), only reachable via Anthropic remote-control.

`/daemon-yolo` — headless plus skip-permissions. Autonomous, phone-only-reachable.

`/window-resume <session-name-or-query>` — reopen an existing session instead of starting a fresh one. Fuzzy-matches the query against spawn labels and each session's first prompt, then relaunches it with `claude --resume <id>` in its **original workspace** (read from the transcript, not guessed) and its **original permission mode** (a YOLO session comes back YOLO). If the session is already alive it refuses to spawn a duplicate and points you at `/window-attach`. After launch it verifies the session is live and reports the permission mode read from the actual process — not the transcript, which can lag. Flags: `--mode <mode>` to force a spawn mode, `--print` to show the resolved command without launching, `--no-verify` to skip the liveness check, `--days N` to widen the lookback (default 14).

`/window-setup` — first-time setup wizard. Five multiple-choice questions, writes the config file.

`/window-list` — show recent spawns and which remote-controlled sessions are still alive. For alive sessions, also shows live status (idle/busy) and age. Filter with `--tag <name>` or `--status idle|busy`.

`/window-kill <session-name>` — terminate a spawned session by its remote-control name. Use `--all` to kill every spawned session, or `--tag <name>` to kill every session in a tag group (e.g. an entire fan-out batch). Accepts either the original name or a local alias set via `/window-rename`.

`/window-rename <current-name> <new-name>` — give a spawned session a friendlier local alias. **LOCAL ONLY**: `/window-list`, `/window-kill`, and `/window-rename` use the new name; claude.ai/code and the mobile app keep showing the original. To get the new name on the web/app too, kill and respawn with `--name`.

`/window-attach <session-name-or-alias>` — bring a spawned session's Windows Terminal window to the foreground. Works on the actual `--remote-control` name or any local alias set via `/window-rename`. Brings the whole WT window forward; if multiple tabs are open, the right tab's title is `<label-or-session-name> | <workspace-name>` so you can spot it visually.

`/window-tag <session-name-or-alias> <tag>` — attach a tag to a spawned session. Prefix the tag with `-` to remove it (e.g. `/window-tag mytab -wip`). Run with no tag to show the session's tags, or `--list` to show every tagged session. Tags are **LOCAL ONLY** and let you group sessions for filtering — see `/window-list --tag <name>`. Tags are stored against the actual session name, so renames don't break them, and killing a session prunes its tags automatically.

`/window-list --tag <name>` — filter the listing to sessions tagged `<name>`. Without `--tag`, `/window-list` shows everything and displays each entry's tags inline.

`/window-status <session-name-or-alias>` — show a live session's state (idle/busy), age since spawn, working directory, and Claude session ID. Use `--all`, `--busy`, or `--idle` to scan everything. This is the read side of the orchestration loop: the answer to "is the session I delegated this to actually done yet?"

`/window-wait <session-name-or-alias>` — block until a session goes idle. Use `--tag <name>` to wait on a whole group instead. `--timeout N` (default 300s) caps how long to wait; `--poll N` (default 2s) controls poll frequency. Exit code 0 = idle reached, 1 = timed out, 2 = bad input. This is what makes the fan-out pattern usable: spawn N tagged workers, then `/window-wait --tag <name>` blocks the orchestrator until they're all done.

`/window-context <session-name-or-alias>` — show recent user/assistant turns from a spawned session's transcript without having to navigate to its terminal tab. `--turns N` (default 3) controls how many turns to print; `--full` disables the per-turn truncation. Works on dead sessions too, as long as the original transcript file still exists at `~/.claude/projects/<sanitized-cwd>/<sessionId>.jsonl`. Closes the orchestration loop with /window-wait: wait for the worker, then read what it produced.

`/window-fanout <N> "<prompt>"` — spawn N worker sessions all running the same first prompt, all auto-tagged together so the whole batch can be waited on, read, and killed as one. Defaults to `--mode window-yolo-remote` (autonomous + remote-controllable). Optional `--tag <name>` overrides the auto-generated batch tag; `--name-prefix <prefix>` controls the per-worker name (default `fanout`, so workers are named `fanout-1`, `fanout-2`, etc.). Capped at N=20 per call. After spawning, prints the exact /window-wait, /window-context, and /window-kill commands for the group.

## Orchestration loop

The full delegate-and-collect pattern using the commands above:

```
/window-fanout 3 "audit the auth code in /src/auth and report any issues" --tag audit
/window-wait --tag audit                  # blocks until all 3 are idle
/window-context fanout-1                  # read worker 1's output
/window-context fanout-2                  # read worker 2's output
/window-context fanout-3                  # read worker 3's output
/window-kill --tag audit                  # clean up the whole group
```

For a single delegated worker, the same pattern works with /window-yolo-remote --name + /window-wait + /window-context.

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

- `~/.claude/commands/window.md` and 16 sibling slash-command files
- `~/.claude/hooks/spawn-window.py` — main launcher (also handles `--resume <id>`)
- `~/.claude/hooks/window-resume.py` — reopen a past session by name in its original workspace + permission mode
- `~/.claude/hooks/window-list.py` — list spawned sessions (supports `--tag` and `--status` filters)
- `~/.claude/hooks/window-kill.py` — terminate spawned sessions (supports `--tag`)
- `~/.claude/hooks/window-rename.py` — give sessions friendly local aliases
- `~/.claude/hooks/window-attach.py` — bring a session's terminal window to the foreground
- `~/.claude/hooks/window-tag.py` — attach grouping tags to spawned sessions
- `~/.claude/hooks/window-status.py` — show a session's live idle/busy state
- `~/.claude/hooks/window-wait.py` — block until a session (or tag group) goes idle
- `~/.claude/hooks/window-context.py` — show recent turns from a session's transcript
- `~/.claude/hooks/window-fanout.py` — spawn N tagged workers with the same first prompt
- `~/.claude/hooks/window_aliases.py` — shared alias-map helpers
- `~/.claude/hooks/window_tags.py` — shared tag-map helpers
- `~/.claude/hooks/agents_state.py` — shared wrapper over `claude agents --json`

`install.ps1` preserves two files if they already exist in `~/.claude/`:
- `window-config.json` — your config (different per machine)
- `commands/window-setup.md` — the setup wizard prompt (often customized per environment, e.g. user name, channel labels)

If you want to refresh either from the repo, delete the file first, then re-run `install.ps1`.

## Uninstall

Delete the 17 files from `~/.claude/commands/` and the 14 files from `~/.claude/hooks/`. Optionally delete `~/.claude/window-config.json`, `~/.claude/window-log.jsonl`, `~/.claude/window-aliases.json`, and `~/.claude/window-tags.json`.

## License

MIT.
