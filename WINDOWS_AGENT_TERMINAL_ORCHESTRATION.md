# Windows Agent Terminal Orchestration

This layer extends the launcher and V1 native console control. It is not a
terminal replacement, daemon, tmux compatibility layer, or WSL dependency.

## Identity and topology

Bridge-created workers have a durable worker identity stored in SQLite. Their
transient AgentRef contains PID, start time, executable identity, and
WT_SESSION when Windows exposes it. A fresh operation revalidates that AgentRef
before writing.

Windows Terminal has no public PID-to-pane API or permanent pane ID. The bridge
creates an opaque window name and unique certificate for each worker. Binding
requires both the certificate in the exact PID-targeted console and exactly one
UI Automation TermControl title in an HWND-scoped bridge-owned Terminal window.
That two-channel proof produces bridge window/tab/pane identities. Runtime IDs
are refreshed after topology changes and are never treated as permanent.

## Controller

hooks/orchestrator.py is the shared CLI used by Codex and by
/agent-orchestrate after installation. It supports worker spawn, task create,
dependencies, verified dispatch, handoff, explicit verification, monitoring,
bounded recovery, safe close, worker/task inventory, and audit output.

Dispatch appends an operation marker and reports COMMAND_EXECUTED only after
the exact target console displays it. Input queuing and quiet screens are never
treated as task completion. The SQLite store (AGENT_ORCHESTRATION_DB, or
%CLAUDE_HOME%/agent-orchestration.db) persists logical workers, AgentRefs,
topology, tasks, dependencies, retry count, and audit records.

## Safety and limitations

- Only certificate-bound bridge workers may be terminated or closed.
- V1 PID/start-time/executable validation rejects PID reuse.
- Ctrl+C remains console-scoped and V1 refuses it if unrelated console
  processes would be affected.
- Failed delivery marks its task blocked.
- A dedicated, certified tab can be closed through its exact UIA tab identity.
  A shared tab is refused while a sibling remains live.

This Terminal build exposes UIA TextPattern for a certified TermControl, so the
bridge reads full attributed scrollback. It does not expose a reliable external
stable pane ID, direct PID-to-pane API, or a pane-local close command that can
be verified: closePane returned success without closing the focused pane.
Pane-close, move, and resize are therefore not represented as successful
operations. Claude slash-command invocation remains a compatibility validation
in the target Claude runtime; it is not inferred from Codex use.
