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
  Dry-verified (`--print` against real transcripts); one real-spawn confirmation
  still recommended before calling it Verified.
- [x] `/window-live` ground-truth process-table query harvested from `live.py` as a
  new command (complementary to `/window-list`, not a replacement). Live-fire
  verified against the real process table (found 7 live claudes incl. profile
  sessions absent from the spawn log; perm/parent/dedup all correct).
- [ ] `find-or-create` brain — not yet started.
- [ ] `claude-session-logger` retirement note — pending after harvest completes.
- [ ] Edward: merge `feat/harvest-resume` -> master + push (prod-action-gate blocks AI).

## Lessons carried in (do not repeat)
- **False YOLO claim**: permission mode IS preserved on resume via the flag; verify
  from process cmdline, never transcript. The retracted warning text is banned here.
- **Cross-workspace silent death**: read `cwd` from transcript JSONL, never decode
  the project-dir slug (lossy).
- **9 empty daemons**: resume uses `claude --resume <id>`, default mode
  `window-remote`, never `/daemon`.
- **Big-transcript timeout**: generous liveness timeout + one retry.

## Next move
Finish the additive `--resume` edits to `spawn-window.py`, write `window-resume.py`
+ `window-resume.md`, update `install.ps1` + README, live-fire test against a real
session, commit on `feat/harvest-resume`. Hand to Edward to push.

## Edward decision needed
None open. Direction (launcher canonical + harvest 3 + drop MCP) approved 2026-05-26.
