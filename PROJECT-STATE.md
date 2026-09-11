# PROJECT-STATE — Windows Agent Terminal Orchestration

**Last verified:** 2026-09-10 (evening, Eastern) · **By:** `/reanchor`

Snapshot. Overwrite on the next reanchor; git holds the history. Every fact names the
command or file it came from. Runtime claims are tagged MEASURED or INFERRED.

## What this project is

The `claude-code-remote-session-launcher` repository is Edward's Windows-native toolkit for
launching, tagging, and controlling Claude and Codex sessions in Windows Terminal. This
branch adds the orchestration layer: one certified MAIN pane that creates a team of
role-addressed worker panes (frontend, backend, reviewer, qa, docs, ops), routes work to
them with proof of execution, hands work to a reviewer for rejection and correction,
recovers a failed worker in place, and tears the whole team down without touching any
pane it does not own. Spec: `WINDOWS_AGENT_TERMINAL_ORCHESTRATION.md`. It is explicitly
not a terminal replacement, daemon, tmux layer, or WSL dependency.

**The promise.** What Edward is buying is trust: he can let an agent drive a team of
sibling terminals on his own desktop and know it will only ever type into, resize, or
close panes it certifiably owns, and that "delivered" means the command actually ran, not
that keystrokes were queued. The product is the bridge (`hooks/orchestrator.py`,
`hooks/worker_runtime.py`, `hooks/terminal_topology.py`, `hooks/terminal_control.py`,
`hooks/team_layout.py`) plus the installed `/agent-orchestrate` command. The live harness
`tests/orchestration_live.py` and the disposable `orch-live-*` databases are scaffolding
that proves the product; they are not the deliverable. "Working" for the user means: a
real Windows Terminal, 1/2/3/4/6 workers, every stage of the harness green, and nothing of
his own left touched or leaked afterwards.

## Current objective

1. Resolve the live 4-worker failure `DELIVERY_UNVERIFIED: INPUT_QUEUED` on the first
   frontend dispatch, without weakening the `DELIVERY_UNVERIFIED` gate.
2. Run full live acceptance sequentially for 1, 2, 3, 4, and 6 workers on the **current**
   source, then commit the dirty worktree and push the branch.

Source: `docs/handoffs/2026-09-10-claude-takeover.md` and Edward's takeover instruction of
2026-09-10.

## Governing requirements and decisions

From the handoff and `docs/superpowers/plans/2026-09-10-main-worker-product-integration.md`:

- Worker binding needs two channels: the unique certificate in the launched PowerShell
  command line and console, plus exactly one matching UIA pane. Pane title alone is never
  enough.
- Only `ORCH_`-certificated processes may be terminated, and only after PID, start time,
  and command line validate. Never touch ordinary PowerShell, Codex, Claude, or Terminal
  tabs.
- `COMMAND_EXECUTED` is reported only after the exact target console shows the marker
  twice (echo plus output). Input queuing and quiet screens are never completion.
- Recovery is in place when the certified transport PID, start time, and command line are
  still alive; it must not race a Terminal pane close.
- Nested Terminal splits get explicit `--size` fractions; a 3-column row uses 2/3 then
  1/2.
- All focus mutations restore the prior foreground window.
- The dirty worktree is intentional. Do not reset, checkout, stash, or discard it.
- Live runs use unique disposable certificates and an isolated database per run.

## Repository

| | |
|---|---|
| Root | `C:/Users/EDWAR/claude-code-remote-session-launcher-windows-agent-terminal-orchestration` — `git rev-parse --show-toplevel` |
| Git common dir | `C:/Users/EDWAR/claude-code-remote-session-launcher/.git` — `git rev-parse --path-format=absolute --git-common-dir` |
| Remote | `github.com/Zbrooklyn/claude-code-remote-session-launcher` — `git remote -v` |
| Project instructions | none; no `CLAUDE.md` or `AGENTS.md` in the repo — `ls` |
| Git hooks | none beyond samples — `ls .git/hooks` |

**Worktrees** — `git worktree list --porcelain`; per-worktree `git -C <path> status --porcelain`

| Path | Branch | Notes |
|---|---|---|
| `…/claude-code-remote-session-launcher` | `master` | clean apart from one untracked plan doc under `docs/`; 1 ahead of `origin/master` |
| `…/claude-code-remote-session-launcher-windows-agent-terminal-orchestration` | `feature/windows-agent-terminal-orchestration` | **the active work**; 11 modified, 4 untracked (see below) |
| `…/claude-code-remote-session-launcher-windows-native-agent-terminal-v1` | `feature/windows-native-agent-terminal-v1` | clean; 4 commits over master; superseded by cherry-picks onto this branch (`git reflog`) |

Branch relationships — `git log --oneline master..HEAD`, `git merge-base`: this branch is
19 commits over `master`, all authored 2026-09-10 between 02:12 and 12:17 Eastern. Its
first four commits are cherry-picks of the v1 branch. Run `git log master..HEAD` for the
list; do not trust hashes written here.

## Remote and pull requests

- `feature/windows-agent-terminal-orchestration` has **no upstream at all** — `git branch -vv`
  shows no `[origin/…]`. All 19 commits plus the dirty worktree exist only on this machine.
- `feature/windows-native-agent-terminal-v1` also has no upstream.
- `master` is 1 commit ahead of `origin/master`.
- Only `origin/master` exists on the remote — `git branch -r`.
- `gh pr list --state all`: PRs #1–#3 merged in May 2026; none for this work.

## Deployed

Not applicable. This is a local developer toolkit installed via `install.ps1`; there is no
hosted environment. Whether Edward's installed copy under `%CLAUDE_HOME%` reflects this
branch was **not checked** this pass.

## Work that exists outside a pushed branch

- **Uncommitted (modified):** `hooks/agent_identity.py`, `hooks/layout_normalizer.py`,
  `hooks/orchestration_store.py`, `hooks/orchestrator.py`, `hooks/team_layout.py`,
  `hooks/terminal_control.py`, `hooks/terminal_topology.py`, `hooks/worker_runtime.py`,
  `tests/test_orchestration_store.py`, `tests/test_orchestrator.py`,
  `tests/test_terminal_topology.py` — `git status`; about 994 insertions, 102 deletions —
  `git diff --stat`. Matches the handoff's list exactly.
- **Untracked:** `docs/handoffs/2026-09-10-claude-takeover.md`,
  `docs/superpowers/plans/2026-09-10-main-worker-product-integration.md`,
  `tests/orchestration_live.py`, `tests/test_team_layout.py`.
- **Stashed:** none — `git stash list` empty.
- **Unpushed:** every commit on both feature branches and 1 on master —
  `git log --branches --not --remotes`.
- **Orphaned:** none — `git fsck --no-reflogs --unreachable --no-progress` returned no commits.
- **Sibling worktree:** `master` checkout has an untracked
  `docs/superpowers/plans/2026-09-10-windows-native-agent-terminal-v1.md`.
- **Line endings:** `git diff` warns LF will become CRLF on every modified file. Not a
  defect today, but the first commit will show this; check `.gitattributes` intent before
  committing.

## Verified state (proof)

- **Unit suite:** 71 passed — `py -3.12 -m pytest -q` run this pass on the dirty worktree.
  MEASURED.
- **Live 1-worker full run PASS** at 20:05 — `%TEMP%\orch-live-full1-inplace4.out`:
  geometry 2160×687, in-place recovery, teardown closed 2. MEASURED, but against source
  **older than the current edits** (see contradictions).
- **Live 2-worker full run PASS** at 20:33 — `%TEMP%\orch-live-matrix.out`: widths
  1076/1076, recovery, teardown closed 3. Same caveat.
- **Live 3-worker full run PASS** at 22:35 — `%TEMP%\orch-live-3e-*.stdout.log`: widths
  717/714/717, heights 687×3, review rejected then corrected, in-place recovery, teardown
  closed 4. Same caveat; `hooks/worker_runtime.py` was edited again at 22:42.
- **Live 4-worker:** two failures. 22:42 `WORKER_DISCONNECTED: BINDING_UNPROVEN:
  certificate is absent from the target console` during create-team
  (`orch-live-4-*.stderr.log`); 22:48 `DELIVERY_UNVERIFIED: INPUT_QUEUED` on the first
  frontend dispatch after create-team and route-work began (`orch-live-4b-*.stderr.log`).
  MEASURED.
- **Live 6-worker:** no run log of any kind exists in `%TEMP%`. Never attempted, or not
  recorded. MEASURED absence of evidence.
- **No leaked processes:** zero processes carry an `ORCH_` certificate in their command
  line once this session's own scanning shell is excluded — `Get-CimInstance Win32_Process`.
  MEASURED. (A first scan showed one hit; it was the scanning shell itself.)
- **No leaked panes (partial):** read-only UIA enumeration of Windows Terminal found two
  active panes, neither titled with `ORCH_`. Inactive tabs are not exposed to that
  enumeration, so this is MEASURED for active tabs and INFERRED for the rest, supported by
  the zero-process result.
- **Leftover harness databases:** seven `%TEMP%\orch-live-*.db` files from runs whose
  `finally` did not complete; every worker row is `ready`, `failed`, `disconnected`, or
  `recovering` and none of their processes exist. Stale files, safe to delete during
  takeover; not deleted this pass.

## Contradictions and unknowns

- **The passing live runs predate the current source.** File mtimes (`ls -lt hooks tests`)
  show `worker_runtime.py` 22:42, `team_layout.py` 22:36, `terminal_control.py` 22:30,
  `orchestrator.py` 22:25, `layout_normalizer.py` 22:19. The 1-, 2-, and 3-worker passes
  ran at 20:05, 20:33, and 22:35. So **no full live run has passed on the code as it
  stands**. The handoff's "verified since the starting commit" list is true of an earlier
  state of the worktree. Every worker count must be re-run.
- **Two different 4-worker failures six minutes apart** (BINDING_UNPROVEN, then
  INPUT_QUEUED) with a `worker_runtime.py` edit between them. INFERRED: the 22:42 rebind
  change fixed the first and exposed or left the second. The second has not been
  reproduced with the before/after console screens the handoff asks for.
- **INPUT_QUEUED with a verify marker covers three distinct situations** in
  `hooks/agentctl.py` `send`: input never reached the console, input echoed but the
  command did not finish inside the 5-second budget in `worker_runtime.send_worker`, or the
  command ran but the marker was not counted twice in the screen read (for example the
  dispatched line wrapping across a row boundary in a narrower or shorter 2×2 pane, so the
  echo half of the marker is split). All INFERRED from source; none observed. The fix must
  distinguish them before touching the gate.
- **The handoff's plan file still shows every task unchecked** in
  `2026-09-10-main-worker-product-integration.md` although Tasks 1–3 are evidently
  implemented and Task 4's harness exists. The plan is stale, not the code.
- **Nothing is pushed.** A machine failure loses the whole day. This contradicts Rule 29
  and is the first safe action of any takeover.
- **A peer session named `brain-04` was busy in the Brain project** when this snapshot was
  taken (`ListAgents`). Its task is unknown; it may or may not touch this repository.
- **Installed copy unchecked.** Whether `%CLAUDE_HOME%` carries this branch's hooks was not
  established.

## Lifecycle phase

**Verify**, with a defect looping back into Build. Define, Decide, Plan, and Design are
settled (spec plus two plan files). Build is complete for Tasks 1–3 and the harness. The
gate to Ship is live acceptance across all five worker counts on the current source,
which has not happened. Recovered from the handoff and the plan files; no
`memory/state-ledger.md` entry exists for this project in Brain.

## Where work continues

1. Push the branch to `origin` as-is, dirty worktree untouched, so the 19 commits are off
   this machine. Reversible; not a gate.
2. Reproduce the 4-worker `INPUT_QUEUED` with a disposable team and capture, per the
   handoff: console screen before and after `send`, `records_written`, console modes,
   PID and start time, and the pane's column and row count. Compare to a 3-worker pane.
3. Write the failing regression test in `tests/test_agentctl.py` or
   `tests/test_orchestrator.py` that pins the real cause, then make the smallest fix that
   keeps `DELIVERY_UNVERIFIED` strict.
4. Run `py -3.12 tests\orchestration_live.py --workers N --stage full` for N in 1, 2, 3,
   4, 6, sequentially, as hidden background processes with separate stdout and stderr
   logs. Each must print `"status": "PASS"` and end with zero `ORCH_` processes.
5. Tick the plan file, commit the worktree in coherent units, push, and update the
   handoff.
