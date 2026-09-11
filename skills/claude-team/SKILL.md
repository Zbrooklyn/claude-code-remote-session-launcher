---
name: claude-team
description: Spin up and run a team of Claude Code worker sessions underneath the current MAIN session, in one Windows Terminal window. Use when the user asks to "spin up a team", "create workers", "start a frontend/backend/database/QA team", "assign this to <role>", "ask <role> to ...", "have QA review ...", "recover a worker", or "close the team". MAIN stays the controller; workers are role-addressed; QA reviews independently; failed work routes back for repair; teardown never touches the user's other sessions.
---

# claude-team

Turn the current Claude Code session (MAIN) into the controller of a team of
Claude worker sessions, each in its own pane below MAIN in the **same** Windows
Terminal window. The user speaks in roles ("tell Frontend...", "have QA review
the backend"); this skill maps that to the orchestration bridge. The user never
sees a PID, HWND, pane id, or terminal command.

Windows only. Requires this repo installed (its `hooks/` on disk). Run every
command below with `py -3.12` from the repo root, capturing JSON output.

## Vocabulary the user will use, and what it maps to

- "spin up a team with Frontend, Backend, Database and QA" -> adopt MAIN, then
  create workers `frontend backend database qa`.
- "tell Backend to ..." / "ask Frontend ..." -> a role-addressed dispatch.
- "have QA review the backend" -> a reviewer verification of the backend task.
- "Frontend and Backend need to agree on the API" -> a worker-to-worker handoff.
- "a worker died / is stuck" -> recover that role.
- "close the team" / "we're done" -> team teardown; MAIN stays.

## One-time per team: adopt MAIN and build the team

MAIN is the session already running. Adopt it (no PID needed - it resolves its
own pane host), then create the requested roles:

```
py -3.12 hooks/orchestrator.py adopt-here MAIN --agent-type claude
# -> {"id": "<MAIN_ID>", ...}. Keep MAIN_ID for the session.

py -3.12 hooks/orchestrator.py team <MAIN_ID> frontend backend database qa \
    --agent-type claude --agent-command "claude --dangerously-skip-permissions --remote-control" \
    --cwd "<project repo path>"
# -> {"workers": [...], "layout": {...}}
```

Notes:
- Roles are whatever the user names; the four above are the website-dev default.
  Three roles, six roles, other names - all fine. Do not hardcode.
- `--cwd` is the project the team is working on, so every worker starts there.
- `--agent-command` is what each worker runs; omit it for plain PowerShell
  workers (used for mechanical tests), or set it to the Claude/Codex launch line.
- The bridge sizes the window so a 2x2 / 2x3 grid has workable pane height.
  It never maximizes to fullscreen and never steals focus.

## Talking to workers (role-addressed; never by PID)

```
# assign work to a role
TASK=$(py -3.12 hooks/orchestrator.py task-create "build the login form" | jq -r .id)
py -3.12 hooks/orchestrator.py dispatch-role frontend $TASK "<instruction>"

# what is everyone doing
py -3.12 hooks/orchestrator.py workers

# read a worker's screen / scrollback is via monitor + the store; MAIN decides.
```

For **powershell** workers the bridge proves the command actually executed
(marker read back from that exact console) - delivery is verified, not queued.
For **claude/codex** workers the instruction is typed into that worker's live
Claude session; completion is judged by explicit evidence (a file written, a
QA read-back), never by the worker merely saying "done".

## QA / independent review and the correction loop

QA is a normal worker whose job is to inspect another worker's output, not to
trust a "done" claim.

```
# QA reviews the backend's task; required_text is the evidence QA must see.
py -3.12 hooks/orchestrator.py verify <TASK_ID> "<evidence string>" --reviewer <QA_ID>
# verified:false -> task returns to "reviewing" (QA rejected).
# route the fix back:
py -3.12 hooks/orchestrator.py handoff-role qa backend <TASK_ID> "<fix instruction>"
# re-verify:
py -3.12 hooks/orchestrator.py verify <TASK_ID> "<evidence string>" --reviewer <QA_ID>
```

MAIN never marks work complete on a worker's say-so; it accepts only on verified
evidence (item: no false completion).

## Dependencies and coordination

```
py -3.12 hooks/orchestrator.py depends <TASK_B> <TASK_A>   # B waits for A
```
Frontend/Backend interface and Backend/Database schema coordination are
worker-to-worker handoffs plus a dependency so the dependent task cannot be
dispatched until its prerequisite is done.

## Recovery (a worker died) - MAIN is never touched

```
py -3.12 hooks/orchestrator.py recover <WORKER_ID>
```
In-place if the certified transport still lives; otherwise a controlled
replacement that keeps the worker's logical role and re-binds its pane.

## Teardown - workers only, MAIN survives

```
py -3.12 hooks/orchestrator.py close-team <MAIN_ID>
# -> {"closed": N, "stopped": [...], "main_preserved": true}
```
Only certificate-bound worker panes are closed, after PID/start-time/command
validation. MAIN's process and tab stay open. If the owned tab holds any pane
the bridge does not own, teardown refuses rather than guess.

## Safety guarantees (always true)

- Only panes/processes this workflow created are ever resized, written to, or
  closed. Never an unrelated Terminal tab, PowerShell, Codex, or Claude session.
- Every worker is bound by a unique certificate in its command line AND its
  console before it is trusted; a PID alone is never enough.
- If a safe action cannot be proven safe, the bridge returns a precise reason
  and refuses, rather than acting.

## Known limitations

- Windows + Windows Terminal only; no WSL/tmux/terminal replacement.
- A window too small for the requested grid yields short panes; the bridge grows
  the window it owns to avoid this. Extremely small monitors may still constrain
  six workers.
- Claude/Codex worker completion is evidence-based, not marker-based; MAIN must
  ask for a concrete artifact or a QA read-back to accept work.
