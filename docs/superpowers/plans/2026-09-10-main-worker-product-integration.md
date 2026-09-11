# MAIN-to-Workers Product Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows-native bridge a complete, safe MAIN-to-workers workflow: create role-addressed teams, route/review/correct work, recover a failed worker into its team, and tear down every owned pane without touching unrelated Terminal state.

**Architecture:** Keep the certified PowerShell process as each worker's control endpoint and retain certificate plus PID/start-time binding. Persist a worker's logical parent so recovery can rejoin the original bridge-owned tab; introduce a coordinated team close that verifies the tab contains only bridge-owned group panes before stopping members and closing the exact tab. Expose team, role addressing, and team teardown through the installed orchestration CLI.

**Tech Stack:** Python 3.12, SQLite, Windows Terminal (`wt.exe`), UI Automation, Win32 console APIs, pytest, PowerShell live acceptance harness.

**Spec:** `WINDOWS_AGENT_TERMINAL_ORCHESTRATION.md`; user acceptance request of 2026-09-10.

## Global Constraints

- Windows-native only; no terminal replacement, WSL, or tmux dependency.
- Every live test uses unique disposable certificates and an isolated orchestration database.
- PID/start-time/image validation and console-wide interrupt refusal remain mandatory.
- All normal Windows Terminal focus mutations restore the prior foreground window.
- A shared tab is closed only when each pane in it belongs to the certified team being closed.
- Test all 1, 2, 3, 4, and 6 worker layouts, role routing, review/correction, recovery, and teardown in the real Terminal.

---

### Task 1: Close the lifecycle model gaps

**Files:**
- Modify: `hooks/orchestration_store.py`
- Modify: `hooks/worker_runtime.py`
- Modify: `hooks/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] Write failing tests for parent persistence, source release on handoff, and safe team teardown refusal.
- [ ] Implement the minimal persistent parent/lifecycle behavior and group teardown verification.
- [ ] Run the focused tests, then `py -3.12 -m pytest -q`.

### Task 2: Expose the product workflow

**Files:**
- Modify: `hooks/orchestrator.py`
- Modify: `commands/agent-orchestrate.md`
- Modify: `README.md`
- Test: `tests/test_orchestrator.py`

- [ ] Write failing tests for role-addressed dispatch/handoff and the CLI parser surface.
- [ ] Add explicit team, role resolution, recovery, wait, and close-team operations without weakening ID-safe calls.
- [ ] Update the command contract and user workflow documentation.
- [ ] Run the focused tests, then the full suite.

### Task 3: Preserve the user's foreground context

**Files:**
- Modify: `hooks/terminal_control.py`
- Test: `tests/test_terminal_topology.py`

- [ ] Write a testable boundary for capture/restore around split focus.
- [ ] Ensure split creation restores the foreground window on success and failure.
- [ ] Run focused tests and the full suite.

### Task 4: Run real Windows Terminal acceptance

**Files:**
- Create: `tests/test_orchestration_live.ps1`
- Modify: `WINDOWS_AGENT_TERMINAL_ORCHESTRATION.md`
- Modify: `docs/superpowers/plans/2026-09-10-main-worker-product-integration.md`

- [ ] Build a self-cleaning disposable harness for 1/2/3/4/6 worker layouts.
- [ ] Prove measured geometry, role-addressed routing, reviewer rejection/correction, explicit verification, recovery, foreground restoration, and no terminal/process leaks.
- [ ] Run acceptance in bounded invocations suitable for the environment's command cutoff; save only concise evidence.
- [ ] Re-run the full automated suite and verify the repository state before committing.
