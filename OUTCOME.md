---
tags:
- type/reference
- project/cofounder
- topic/outcome
- status/active
---
# Project Outcome — Claude Code Remote Session Launcher

> Canonical repo: `https://github.com/Zbrooklyn/claude-code-remote-session-launcher`
> Decision (2026-05-26): this repo is the **canonical** session-management tool.
> The sibling `claude-session-logger` is being **retired** — its 3 genuinely-unique
> capabilities are being harvested into this repo's slash-command + hook idiom.

## Desired result
A dependable, public-shippable tool that lets any Claude Code session spawn, see,
resume, and manage the full population of Claude Code sessions on the machine —
driven by slash commands from inside a session, installed via `install.ps1` into
`~/.claude/`. It must be reliable enough that Edward depends on it daily AND that a
stranger can install it from GitHub and have it work on a fresh machine.

## Look
Command-line / slash-command surface. No GUI. Output is plain ASCII tables and
clear status lines (the existing `/window-list`, `/window-status` house style).
The README is the product's face — clean, complete, honest about limitations.

## Feel
Dependable and honest. No claims that outrun what the code does (the entire
project's pain has come from docs/claims drifting from reality). A stranger reading
the README should trust every sentence. Calm, precise, no hype.

## Experience
1. Clone, run `./install.ps1` in PowerShell 7, run `/window-setup` (5 questions).
2. `/window` (and family) spawn fresh sessions; `/window-resume <name>` reopens a
   past session in its original workspace with its original permission mode intact.
3. `/window-list` shows what's actually alive (ground-truth, not a stale log).
4. The orchestration loop (`/window-fanout → /window-wait → /window-context →
   /window-kill`) lets a session delegate work to N workers and collect results.
5. Stranger walks away thinking: "this just worked, and the README didn't lie."

## Success criteria
- `/window-resume <name>` reopens the correct session, in the correct `cwd` (read
  from transcript, never slug-decoded), with the original permission mode preserved
  and **verified from the live process command line** (not the transcript).
- Resuming a YOLO session comes back YOLO (`--dangerously-skip-permissions` passed).
- All existing spawn commands behave identically after the `--resume` extension
  (additive change, default None).
- `install.ps1` installs the new command + hook; README documents it accurately.
- Public GitHub `master` contains no false claims (the retracted "Anthropic
  downgrades YOLO on resume" text must never appear here).
- Live-fire tested against a real session before any "ready" claim.

## Non-goals
- Not porting the `claude-session-logger` Python package wholesale (architecture
  clash — harvest the unique 20%, drop the redundant 80%).
- Not keeping the MCP server — slash commands are already agent-callable.
- Not cross-platform yet — Windows-only is an accepted current constraint.
- Not a GUI.

## Constraints
- Windows-only (wt.exe, claude.exe, PowerShell 7 for installer).
- `prod-action-gate.py` blocks the AI from `git push origin master` — **Edward
  pushes**. The AI's work ends at a committed branch.
- Build in the launcher's own idiom (command `.md` + Python hook + shared
  underscore-named helpers), never graft a foreign architecture in.

## Current gap (live)
- [x] `/window-resume` harvested. `spawn-window.py` extended with additive
  `--resume`; `window-resume.py` + command + README done. Committed `bb89141`.
  Every link independently verified: --resume arg construction (unit test);
  find + cwd-read + mode-decision + command construction (--print on real
  sessions telegram/hermes/bbw); session registration timing ~10s (well within
  the 25/40s liveness timeout); the launch path is the same one the 6 working
  spawn commands use. NOT yet observed as one integrated real-session resume,
  because the only realistic target is one of Edward's actual (often YOLO)
  conversations, and auto-resuming a YOLO session risks it auto-continuing work.
  Cleanest true proof = Edward runs `/window-resume <name>` on a session he picks.
- [x] BUG FOUND BY TESTING + FIXED: liveness was judged by whether a
  `~/.claude/sessions/*.json` file exists, but those files linger after a hard
  kill/crash -> dead sessions read as alive. `window_sessions.alive_session_ids`
  / `alive_pid_for_session` now cross-check the OS process table (only a running
  pid counts). Verified: a killed session now correctly flips to dead.
- [x] `/window-live` ground-truth process-table query harvested from `live.py` as a
  new command (complementary to `/window-list`, not a replacement). Live-fire
  verified against the real process table (found 7 live claudes incl. profile
  sessions absent from the spawn log; perm/parent/dedup all correct).
- [x] `find-or-create` harvested as `/window-find` + shared `window_sessions.py`
  (extracted from window-resume; window-resume refactored to use it, regression
  re-verified identical). The gate is a mechanism: `/window-find` lists matches +
  routes (resume / attach-if-live / spawn) but never acts. find-or-confirm-or-ask
  protocol documented in README. Live-fire verified: `bbw` correctly routed to
  attach (already live, no duplicate), `telegram` to resume, nonsense to spawn.
- [x] **SHIPPED v1.0.0 (2026-05-27).** PR #1 merged to master (aa614f7c). Release
  `v1.0.0` published. CI green on Ubuntu + Windows. 29-test suite + cross-platform CI.
- [x] Resume real-spawn confirmation — DONE live: `claude --resume <id>` reattached
  to the exact session (id `0bb2113e`, correct cwd, recovered original name).
  Surfaced + fixed a double-spawn bug (slow cold-boot > first liveness timeout);
  regression-tested.
- [ ] `claude-session-logger` retirement note — still open. Recommendation: add a
  deprecation banner to its README pointing here, then archive the repo on GitHub
  (reversible). Separate repo; not part of the v1.0.0 ship.

## Lessons carried in (do not repeat)
- **False YOLO claim**: permission mode IS preserved on resume via the flag; verify
  from process cmdline, never transcript. The retracted warning text is banned here.
- **Cross-workspace silent death**: read `cwd` from transcript JSONL, never decode
  the project-dir slug (lossy).
- **9 empty daemons**: resume uses `claude --resume <id>`, default mode
  `window-remote`, never `/daemon`.
- **Big-transcript timeout**: generous liveness timeout + one retry.

## Next move
Shipped. Only remaining (optional) item: retire `claude-session-logger` (README
deprecation banner + archive on GitHub).

## Edward decision needed
None open. Direction (launcher canonical + harvest 3 + drop MCP) approved 2026-05-26.
v1.0.0 shipped 2026-05-27.
