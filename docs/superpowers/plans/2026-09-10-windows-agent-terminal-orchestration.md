# Windows Agent Terminal Orchestration Implementation Plan

Goal: Build a Windows-native persistent orchestration layer that maps, controls, monitors, and verifies multiple Claude/Codex workers in Windows Terminal.

Architecture: Extend V1 PID-safe console control with a topology provider that owns stable window/tab/pane bridge IDs. Persist logical workers, tasks, operations, and verification in a small SQLite store. A short-lived CLI calls these modules; no terminal replacement or daemon is introduced.

Constraints:

- Windows-native only; do not add tmux, WSL, Zellij, psmux, Herdr, or a replacement terminal.
- Use uniquely marked disposable sessions for every mutation test.
- Retain V1 PID/start-time validation and console-wide interrupt safety.
- Do not build orchestration on topology until the Stage 1 bridge is live-proven.

## Checklist

- [ ] Establish topology bridge in hooks/terminal_topology.py and live-prove exact pane-to-agent mapping.
- [ ] Add exact safe Terminal controls in hooks/terminal_control.py only where stable topology supports them.
- [ ] Add SQLite workers/tasks/dependencies/audit persistence in hooks/orchestration_store.py and hooks/orchestration_models.py.
- [ ] Add orchestration controller and shared CLI in hooks/orchestrate.py and hooks/worker_runtime.py.
- [ ] Reuse launcher aliases, live state, status, wait, context, fan-out, and spawn hooks rather than duplicate them.
- [ ] Add unit tests for identity, topology, terminal control, persistence, dependencies, retries, and verification states.
- [ ] Run disposable PS 5.1/PS 7 end-to-end acceptance with focus/minimize, handoff, review, recovery, and cleanup.
- [ ] Document actual architecture and limitations in WINDOWS_AGENT_TERMINAL_ORCHESTRATION.md.
