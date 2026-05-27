#!/usr/bin/env python3
"""window-live.py -- ground-truth view of what Claude sessions are ACTUALLY
running right now, straight from the OS process table.

Where /window-list answers "what did I spawn recently?" (from the spawn log,
which can be stale or miss sessions started another way), this answers "what
is alive at this exact moment?" by enumerating claude.exe processes directly
and reconciling them against ~/.claude/sessions/*.json. It is the tool for
verifying live-vs-dead-vs-duplicate when the spawn log and reality disagree.

What it shows that the log-based view can't:
  - sessions started ANY way (not just via /window), including plain `claude`
  - duplicate processes sharing one session id (collapsed, with a DUP count)
  - the permission mode each process is ACTUALLY running with (read from its
    command line -- ground truth, not the transcript which can lag)
  - user-visible sessions (parent is a terminal) vs background workers
  - idle/busy + age, when `claude agents --json` knows the session

Usage:
  python window-live.py            # compact: user-visible sessions, one row each
  python window-live.py -v         # verbose: include background workers, PIDs, parents
  python window-live.py --json     # machine-readable, for agent consumption

Cross-platform: Get-CimInstance on Windows, /proc + ps on POSIX.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from agents_state import by_remote_control_name, format_age  # noqa: E402
except Exception:  # pragma: no cover - agents_state is best-effort enrichment
    def by_remote_control_name():
        return {}
    def format_age(_ms, _now=None):
        return "?"

SESSIONS_DIR = Path.home() / ".claude" / "sessions"


@dataclass
class LiveSession:
    session_id: str
    pids: list[int] = field(default_factory=list)
    primary_pid: int | None = None
    name: str | None = None
    workspace: str | None = None
    permission_mode: str | None = None
    remote_control_name: str | None = None
    parent_process: str | None = None
    user_visible: bool = True
    duplicate_pids: list[int] = field(default_factory=list)
    status: str | None = None       # idle / busy, from agents_state
    started_at: int | None = None


def _query_all_claudes() -> list[dict]:
    """Raw ProcessId / ParentProcessId / ParentName / CommandLine per claude.exe."""
    if sys.platform == "win32":
        ps_cmd = (
            "$procs = Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\";"
            "$results = foreach ($p in $procs) {"
            "  $parent = Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.ParentProcessId)\" -ErrorAction SilentlyContinue;"
            "  [PSCustomObject]@{"
            "    ProcessId = $p.ProcessId;"
            "    ParentProcessId = $p.ParentProcessId;"
            "    ParentName = if ($parent) { $parent.Name } else { $null };"
            "    CommandLine = $p.CommandLine"
            "  }"
            "};"
            "$results | ConvertTo-Json -Compress -Depth 3"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
            )
            data = json.loads(result.stdout or "[]")
        except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            return [data]
        return data if isinstance(data, list) else []
    # POSIX
    out: list[dict] = []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid,comm,args"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, _comm, args = parts
        if "claude" not in args.lower():
            continue
        pname = None
        try:
            pr = subprocess.run(["ps", "-p", ppid, "-o", "comm="],
                                capture_output=True, text=True, timeout=5)
            pname = pr.stdout.strip() or None
        except Exception:
            pass
        out.append({"ProcessId": int(pid), "ParentProcessId": int(ppid),
                    "ParentName": pname, "CommandLine": args})
    return out


_TERMINAL_PARENTS = {
    "WindowsTerminal.exe", "wt.exe", "OpenConsole.exe", "conhost.exe",
    "powershell.exe", "pwsh.exe", "cmd.exe",
    "tmux", "screen", "iterm2", "iterm", "Terminal", "gnome-terminal",
    "konsole", "xterm", "alacritty", "kitty",
}


def _is_user_visible(parent_name: str | None) -> bool:
    return bool(parent_name) and parent_name in _TERMINAL_PARENTS


def get_live_sessions() -> list[LiveSession]:
    procs = _query_all_claudes()

    # pid -> session metadata, from ~/.claude/sessions/*.json
    meta_by_pid: dict[int, dict] = {}
    if SESSIONS_DIR.is_dir():
        for f in SESSIONS_DIR.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            pid = d.get("pid")
            if pid:
                meta_by_pid[int(pid)] = d

    agents = by_remote_control_name()  # remote_control_name -> agent state

    by_sid: dict[str, LiveSession] = {}
    for p in procs:
        try:
            pid = int(p.get("ProcessId", 0))
        except (TypeError, ValueError):
            continue
        if not pid:
            continue
        cmdline = p.get("CommandLine") or ""
        parent = p.get("ParentName")

        meta = meta_by_pid.get(pid, {})
        sid = meta.get("sessionId")
        if not sid:
            continue  # background claude with no session metadata — not tracked

        rc_match = re.search(r"--remote-control\s+(\S+)", cmdline)
        rc_name = rc_match.group(1).strip('"') if rc_match else None

        if "--dangerously-skip-permissions" in cmdline:
            perm = "bypassPermissions"
        else:
            pm = re.search(r"--permission-mode\s+(\S+)", cmdline)
            perm = pm.group(1) if pm else "default"

        entry = by_sid.get(sid)
        if entry is None:
            entry = LiveSession(session_id=sid, primary_pid=pid)
            entry.pids.append(pid)
            entry.name = meta.get("name")
            entry.workspace = (meta.get("cwd") or "").replace("\\", "/") or None
            entry.permission_mode = perm
            entry.remote_control_name = rc_name
            entry.parent_process = parent
            entry.user_visible = _is_user_visible(parent)
            by_sid[sid] = entry
        else:
            entry.duplicate_pids.append(pid)
            if rc_name and not entry.remote_control_name:
                entry.remote_control_name = rc_name
                entry.primary_pid = pid
                entry.permission_mode = perm
                entry.parent_process = parent
                entry.user_visible = _is_user_visible(parent)

        # Enrich idle/busy + age from agents_state by remote-control name.
        if rc_name and rc_name in agents:
            a = agents[rc_name]
            entry.status = a.get("status")
            entry.started_at = a.get("startedAt")

    return sorted(by_sid.values(), key=lambda s: (not s.user_visible, s.name or "~~"))


_PERM_SHORT = {
    "bypassPermissions": "YOLO", "default": "def", "acceptEdits": "edit",
    "plan": "plan", "auto": "auto", "dontAsk": "dnt",
}


def render(sessions: list[LiveSession], verbose: bool = False) -> str:
    if not sessions:
        return "No live Claude sessions right now."
    lines: list[str] = []
    if verbose:
        lines.append(f"{'PID':>6}  {'SID':10}  {'V':1}  {'PERM':>4}  {'ST':4}  {'NAME':32}  {'PARENT':20}  {'DUP':>3}  WORKSPACE")
        lines.append("-" * 150)
        for s in sessions:
            v = "U" if s.user_visible else "B"
            perm = _PERM_SHORT.get(s.permission_mode or "", "?")
            st = (s.status or "")[:4]
            nm = (s.name or s.remote_control_name or "(unnamed)")[:32]
            parent = (s.parent_process or "?")[:20]
            dup = str(len(s.duplicate_pids)) if s.duplicate_pids else ""
            ws = (s.workspace or "")[-44:]
            lines.append(f"{s.primary_pid:>6}  {s.session_id[:10]}  {v:1}  {perm:>4}  {st:4}  {nm:32}  {parent:20}  {dup:>3}  {ws}")
    else:
        lines.append(f"{'#':>2}  {'SID':10}  {'PERM':>4}  {'ST':4}  {'NAME':34}  WORKSPACE")
        lines.append("-" * 120)
        visible = [s for s in sessions if s.user_visible]
        for i, s in enumerate(visible, 1):
            perm = _PERM_SHORT.get(s.permission_mode or "", "?")
            st = (s.status or "")[:4]
            nm = (s.name or s.remote_control_name or "(unnamed)")[:34]
            ws = (s.workspace or "")[-50:]
            dup = f"  (+{len(s.duplicate_pids)} dup PID)" if s.duplicate_pids else ""
            lines.append(f"{i:>2}  {s.session_id[:10]}  {perm:>4}  {st:4}  {nm:34}  {ws}{dup}")
        bg = sum(1 for s in sessions if not s.user_visible)
        if bg:
            lines.append("")
            lines.append(f"(plus {bg} background/worker claude(s) -- use -v to see)")
    return "\n".join(lines)


def to_dict(sessions: list[LiveSession]) -> list[dict]:
    return [{
        "session_id": s.session_id,
        "name": s.name,
        "remote_control_name": s.remote_control_name,
        "workspace": s.workspace,
        "permission_mode": s.permission_mode,
        "status": s.status,
        "primary_pid": s.primary_pid,
        "duplicate_pids": s.duplicate_pids,
        "parent_process": s.parent_process,
        "user_visible": s.user_visible,
    } for s in sessions]


def main() -> int:
    argv = sys.argv[1:]
    verbose = any(a in ("-v", "--verbose") for a in argv)
    as_json = "--json" in argv
    sessions = get_live_sessions()
    if as_json:
        print(json.dumps(to_dict(sessions), indent=2))
        return 0
    print(render(sessions, verbose=verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
