# Claude multi-session orchestration — architecture, commands, and acceptance

Source-of-truth document for the MAIN-to-workers orchestration on Windows
Terminal. Windows only; no WSL, tmux, or terminal replacement.

## What it is

One MAIN Claude session controls a team of worker sessions, each in its own pane
below MAIN in the same Windows Terminal window. MAIN addresses workers by role,
routes work with proof of delivery, coordinates dependencies, runs an
independent QA review-and-correct loop, recovers a failed worker, and tears the
team down without touching anything it does not own.

The reusable natural-language layer is the `claude-team` skill
(`skills/claude-team/SKILL.md`). Everything below the skill is the bridge in
`hooks/`.

## Architecture

- **Identity (`hooks/agent_identity.py`)** — a worker's transient AgentRef is
  PID + start time + image + command line; every mutation re-validates it, so
  PID reuse is rejected.
- **Certificate binding (`hooks/terminal_topology.py`)** — a worker is trusted
  only when its unique certificate appears both in its console and in exactly one
  UI Automation pane. A pane title alone is never enough. MAIN, which is an
  existing session with no launch certificate, is adopted by writing the
  certificate as its console title instead (`worker_runtime.adopt_main`).
- **Console I/O (`hooks/native_console.py`)** — attach to the exact PID's
  console, write input records, read the visible screen, read console modes and
  dimensions. Detach after each operation.
- **Delivery + verification (`hooks/agentctl.py`, `hooks/worker_runtime.py`)** —
  a PowerShell dispatch appends an operation marker and is reported
  COMMAND_EXECUTED only after that exact console echoes the marker twice (the
  command echo plus its output). Input queuing is never called completion. A
  console momentarily one row tall (just after a split/normalization) is allowed
  to settle before writing; a genuinely too-small pane times out and returns
  INPUT_QUEUED with queued_reason PANE_TOO_SHORT.
- **Layout (`hooks/team_layout.py`, `hooks/layout_normalizer.py`)** — MAIN on
  top, workers in a balanced grid below, normalized from measured UIA geometry.
  The owned window is grown to the monitor work area first
  (`terminal_control.ensure_window_area`) so grid panes are tall enough to run a
  command.
- **Store (`hooks/orchestration_store.py`)** — SQLite: logical workers, roles,
  parent links, tasks, dependencies, retries, audit. Roles are the address MAIN
  uses; runtime IDs are never treated as stable.
- **Controller (`hooks/orchestrator.py`)** — the CLI that composes all of it.

## Commands (all: `py -3.12 hooks/orchestrator.py <cmd>`)

- `adopt-here <name> [--agent-type claude]` — adopt the calling MAIN session.
- `adopt-main <name> <pid> [--agent-type]` — adopt a specific pane host.
- `team <main_id> <role...> [--agent-type] [--agent-command] [--cwd]` — build the
  worker grid below MAIN.
- `dispatch-role <role> <task_id> <instruction>` / `dispatch <worker_id> ...`
- `handoff-role <src_role> <dst_role> <task_id> <instruction>` / `handoff ...`
- `verify <task_id> <required_text> [--reviewer <id>]` — evidence-based review.
- `task-create`, `depends`, `monitor`, `wait`, `recover`, `close`, `close-team`,
  `workers`, `tasks`, `audit`.

## Tests

- **Unit:** `py -3.12 -m pytest -q` — 81 tests over identity, topology,
  persistence, delivery states, adoption, short-pane diagnosis, layout, teardown.
- **Live acceptance (real Windows Terminal):**
  `py -3.12 tests/orchestration_live.py --workers <1|2|3|4|6> --stage full` —
  geometry, role routing, review/correction, in-place recovery, foreground
  restoration, certified teardown, no leaks.
- **Behavioural contract:** `py -3.12 tests/acceptance_contract.py --workers 4`
  — per-capability evidence for the 100-item acceptance checklist.

## Known limitations

- Windows + Windows Terminal only.
- Layout normalization for multi-row grids (four and six workers) is slow:
  several minutes per full run, dominated by repeated UIA resize passes. It is
  correct, not fast.
- Claude/Codex worker completion is evidence-based (an artifact or a QA
  read-back), not marker-based; MAIN must not accept a bare "done".
- A monitor too small for the requested grid yields short panes; the bridge
  grows its own window to avoid this, but cannot exceed the physical work area.

## Acceptance state

The filled 100-item checklist, its evidence, and the current pass/partial/fail
totals live in `docs/ACCEPTANCE-CHECKLIST.md`, regenerated from the live and
behavioural runs. That file is the authoritative acceptance record; this file is
the architecture and command reference behind it.
