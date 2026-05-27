# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow [SemVer](https://semver.org/).

## [1.0.0] - 2026-05-27

First stable release. The launcher can now see, find, and resume the full
population of Claude Code sessions on the machine — not just spawn new ones.

### Added
- **`/window-resume <name|id>`** — reopen a past session by fuzzy name or
  session-id prefix. Reads the session's own `cwd` and original permission mode
  from its transcript, relaunches in the right directory, preserves YOLO when
  the original was YOLO, and verifies the resumed process is actually live
  before reporting success. Already-running matches route to `/window-attach`
  instead of spawning a duplicate.
- **`/window-live`** — ground-truth "what's running right now," read from the
  process table rather than metadata files (which linger after a crash/kill).
  Shows permission mode, parent, and user-visible vs. background, deduped by
  session id. `-v` / `--json`.
- **`/window-find <name>`** — the find-or-confirm-or-ask gate. Lists matching
  sessions marked live/off and prints the exact next command (resume / attach /
  spawn) but never acts on its own — so an agent looks up whether a session
  exists before creating one. `--json` returns `next_step` + `resume_command`.
- **`claude_env.py`** — portable `claude` binary discovery (PATH → known install
  locations → `CLAUDE_BINARY` override) and `claude_home()` config-dir resolution
  (honors `$CLAUDE_HOME`). Replaces the previously hardcoded binary path so the
  tool works on a stranger's machine, not just the author's.
- **`window_sessions.py`** — shared session-catalog + fuzzy-match + liveness
  layer imported by both `window-resume` and `window-find`, so their matching
  can never drift apart.
- **Test suite** (`tests/`) — 25 pytest cases over discovery, catalog/match,
  process-verified liveness, and argument/command construction, running against
  an isolated `$CLAUDE_HOME`. CI runs them on Ubuntu and Windows.

### Changed
- `spawn-window.py` and `agents_state.py` now resolve the `claude` binary via
  `claude_env` instead of a hardcoded `~/.local/bin/claude.exe`.
- Liveness everywhere is now process-verified: a `sessions/*.json` metadata file
  only counts as "alive" if its pid is in the live process table.

### Fixed
- Dead sessions left behind stale `sessions/*.json` files and were reported as
  alive. Liveness now cross-checks the process table.
- `/window-resume` could open a *second* window onto the same session when claude
  cold-boot took longer than the first liveness timeout (the prior spawn
  registered late, so the retry fired anyway). The loop now re-checks liveness
  before re-spawning and waits longer on the first attempt. Found via live-fire
  resume on a slow machine; covered by a regression test.
