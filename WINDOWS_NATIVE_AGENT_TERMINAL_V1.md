# Windows-Native Agent Terminal Control V1

V1 extends the existing launcher; it does not replace Windows Terminal or build a multiplexer. `agentctl.py` is a short-lived native controller shared by Claude slash commands and Codex shell use.

## Addressing and safety

An `AgentRef` contains PID, process creation time, executable image, parent, command line, and `WT_SESSION` when the target exposes it. Mutating operations revalidate PID + start time + executable immediately before attaching. A missing or reused target is reported as `STALE_TARGET`, never silently retargeted.

```powershell
py hooks/agentctl.py list --json
py hooks/agentctl.py inspect <pid-or-session-name> --json
py hooks/agentctl.py read <target> --json
py hooks/agentctl.py send <target> "Write-Output 'marker'" --enter --verify marker --json
py hooks/agentctl.py key <target> enter --json
py hooks/agentctl.py interrupt <target> --json
```

`send --verify` requires this operation to add the marker twice to the screen buffer: PowerShell's echoed command and its output. A successful Win32 write alone is only `INPUT_QUEUED`, not command completion. `interrupt` refuses when console membership includes a process other than the target and short-lived controller.

## Launcher integration and boundary

`/window-send`, `/window-screen`, and `/window-interrupt` wrap the shared CLI. Existing session discovery, aliases, tags, status, wait, transcript context, fan-out, resume, and kill hooks are reused. `agentctl wait` uses `claude agents --json` for existing remote-control Claude sessions.

V1 does not manage Windows Terminal tabs or panes. Windows Terminal exposes no stable external PID or `WT_SESSION` to pane identity; that bridge is V2. There is no daemon, terminal replacement, or tmux compatibility layer.

Claude invoking this shared CLI is a deferred compatibility validation. The
native helper and Codex path are verified; Claude parity is currently
**UNVERIFIED** because the installed Claude CLI reached its usage limit before
the disposable parity command could run.

## Baseline repair record

Before V1, six failures were stale tests: four expected the older five-value `spawn-window.parse_args` result instead of its intentional launch-group value, and two mocked the older PID-only liveness helper instead of the intentional command-line-aware `running_claude_procs`. Production launcher behavior was not changed; the baseline became 29/29.
