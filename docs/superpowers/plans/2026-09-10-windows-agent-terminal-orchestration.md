# Windows Agent Terminal Orchestration Implementation Plan

Goal: Build a Windows-native persistent orchestration layer that maps, controls, monitors, and verifies multiple Claude/Codex workers in Windows Terminal.

Architecture: Extend V1 PID-safe console control with a topology provider that owns stable window/tab/pane bridge IDs. Persist logical workers, tasks, operations, and verification in a small SQLite store. A short-lived CLI calls these modules; no terminal replacement or daemon is introduced.

Constraints:

- Windows-native only; do not add tmux, WSL, Zellij, psmux, Herdr, or a replacement terminal.
- Use uniquely marked disposable sessions for every mutation test.
- Retain V1 PID/start-time validation and console-wide interrupt safety.
- Do not build orchestration on topology until the Stage 1 bridge is live-proven.

## Checklist

- [x] Establish topology bridge in hooks/terminal_topology.py and live-prove exact pane-to-agent mapping.
- [x] Add exact safe Terminal controls in hooks/terminal_control.py where stable topology supports them.
- [x] Add SQLite workers/tasks/dependencies/audit persistence in hooks/orchestration_store.py.
- [x] Add orchestration controller and shared CLI in hooks/orchestrator.py and hooks/worker_runtime.py.
- [x] Reuse V1 process identity, console control, and launcher installation rather than duplicate them.
- [x] Add unit tests for topology, persistence, dependencies, delivery failure, retries, and verification states.
- [x] Run disposable PS 5.1/PS 7 end-to-end acceptance with background/minimize, handoff, review, recovery, and cleanup.
- [x] Document actual architecture and limitations in WINDOWS_AGENT_TERMINAL_ORCHESTRATION.md.
