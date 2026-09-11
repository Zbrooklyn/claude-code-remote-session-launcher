# Claude takeover — Windows Agent Terminal Orchestration

## Canonical state

- Repository: `C:\Users\EDWAR\claude-code-remote-session-launcher-windows-agent-terminal-orchestration`
- Branch: `feature/windows-agent-terminal-orchestration`
- Starting commit: `6ca3f1c relax measured worker rows to equal widths`
- The worktree is intentionally dirty. Preserve every listed change; none has been committed or pushed yet.
- At handoff time, no process with an `ORCH_` certificate remained. The last failed disposable acceptance team completed its harness cleanup.

## Mission

Deliver and prove the real Windows-native MAIN-to-workers workflow: certified MAIN identity, 1/2/3/4/6-worker layouts, role routing, reviewer correction, in-place recovery, foreground restoration, and safe no-leak teardown. Do not substitute unit-test success for live Windows Terminal proof.

## Verified since the starting commit

- `py -3.12 -m pytest -q` passed with **71 tests** after the latest source edits.
- A full 3-worker disposable live run passed:
  - worker geometry `717/714/717` px, heights `687/687/687`;
  - frontend route verification;
  - reviewer rejection then correction;
  - same-PID `in_place_transport` recovery;
  - foreground check;
  - certified teardown closed MAIN plus three workers with no `ORCH_` process left.
- A live three-worker construction probe, without normalization, measured equal worker widths `717/714/717` and successfully certificate-tore down all four owned processes.
- A live four-worker construction snapshot measured a correct `2 x 2` worker grid: widths `1078/1078`, heights `338/341`.
- A visual capture of the user-facing Codex tabs established that the manually active/verbose tab and launched tab both use native `codex.exe` 0.154.0. A fresh Codex TUI is sparse until it has a conversation/tool history; do not call a launch visually verified from process evidence alone.

## Important implementation decisions already made

- Initial worker binding requires two channels: unique certificate in the launched PowerShell command line and console, plus exactly one matching UIA pane.
- Runtime IDs are volatile. Resize is now scoped to the owned window and can rebind to the unique certificate pane on UIA redraw.
- Recovery is in-place when the certified worker transport PID/start-time/command line remains alive. It must not race Terminal pane close.
- Team teardown now maps all live panes by unique certificates in one tab before stopping exact certificate-bound PIDs. It no longer depends on transient Terminal text read-back.
- `refresh_worker_topology` was changed to rebind a previously two-channel-bound worker via: same PID/start-time/command-line certificate + one unique certificate pane in the original owned window. It deliberately does not use a pane title alone.
- Nested Windows Terminal splits must receive explicit `--size` fractions. For a 3-column worker row, the second and third workers use `2/3` and `1/2` of the current nested pane. Default splits created `1/2,1/4,1/4` geometry.

## Current blocker — reproduced live, not resolved

The latest **4-worker full** live run reached correct team creation and `route-work`, then failed on the first frontend task delivery:

```
OrchestrationError: DELIVERY_UNVERIFIED: INPUT_QUEUED
```

`control.dispatch_role("frontend", ..., "Write-Output 'FRONTEND_…'")` calls `send_worker`, which uses the native-console input path. The expected result is `COMMAND_EXECUTED`; it returned `INPUT_QUEUED`.

The run's finally cleanup executed, and a subsequent `ORCH_` command-line process scan was empty. Treat this as an input/read-back timing or delivery issue; do not weaken `DELIVERY_UNVERIFIED` merely to pass acceptance.

## Recommended immediate investigation

1. Start with `hooks/agentctl.py:send`, `hooks/native_console.py`, and `hooks/worker_runtime.py:send_worker`.
2. Reproduce against a disposable 4-worker team, with a unique `Write-Output` marker. Capture the native console `before` and `after` screens, records written, console modes, and exact PID/start time.
3. Compare against the previous successful 3-worker run. The likely difference is focus/UIA redraw after the new refresh behavior, not role routing semantics.
4. Add a failing automated regression test before source changes, then prove the live 4-worker route returns `COMMAND_EXECUTED` and verifies the marker.
5. Rerun full acceptance sequentially for **1, 2, 3, 4, and 6** workers. Each run uses:

   ```powershell
   py -3.12 tests\orchestration_live.py --workers <1|2|3|4|6> --stage full
   ```

   If the shell truncates a long foreground command, launch it as a hidden background process with separate temp stdout/stderr logs and poll; do not kill it without performing certificate-bound cleanup.

## Safety and cleanup rules

- Never touch ordinary user PowerShell, Codex, Claude, or Windows Terminal tabs. Target only an `ORCH_` certificate after validating PID, start time, and command line.
- If a disposable harness is forcibly stopped and its `finally` does not run, open its isolated `%TEMP%\orch-live-*.db`, enumerate workers, and use `terminate_worker` only after certificate validation. Then prove no matching `ORCH_` processes remain.
- Do not reset, checkout, or discard the dirty worktree.

## Files materially changed this pass

- `hooks/agent_identity.py`
- `hooks/layout_normalizer.py`
- `hooks/orchestration_store.py`
- `hooks/orchestrator.py`
- `hooks/team_layout.py`
- `hooks/terminal_control.py`
- `hooks/terminal_topology.py`
- `hooks/worker_runtime.py`
- `tests/orchestration_live.py`
- `tests/test_orchestration_store.py`
- `tests/test_orchestrator.py`
- `tests/test_terminal_topology.py`
- `tests/test_team_layout.py` (new)
- `docs/superpowers/plans/2026-09-10-main-worker-product-integration.md` (new)

