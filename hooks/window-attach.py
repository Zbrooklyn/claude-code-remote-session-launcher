#!/usr/bin/env python3
"""window-attach.py -- bring a spawned session's Windows Terminal window to the front.

Usage:
  python window-attach.py <session-name-or-alias>

How it works:
  1. Resolve alias -> actual session name (the --remote-control value).
  2. Find the claude.exe process whose argv has "--remote-control <name>".
  3. Walk parent process IDs upward to find WindowsTerminal.exe.
  4. Call Win32 SwitchToThisWindow on its main window handle.

Caveat: a single WindowsTerminal.exe window can host many tabs. This script
brings the WINDOW forward; the right TAB has its title set by spawn-window.py
to "<label-or-session-name> | <workspace-name>" so you can spot it visually.
True per-tab focus would need Windows Terminal's JSON-RPC API (not yet stable).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from window_aliases import load_aliases, resolve_to_actual  # noqa: E402

LOG_PATH = Path.home() / ".claude" / "window-log.jsonl"


def lookup_title_for(actual_name: str) -> str | None:
    """Most recent WT tab title for this session, if logged.

    spawn-window.py uses `label or sess_name` as title_id, so we mirror that.
    Returns just the title_id (no workspace suffix), or None if unknown.
    """
    if not LOG_PATH.is_file():
        return None
    last_title: str | None = None
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("session_name") != actual_name:
                    continue
                last_title = e.get("label") or actual_name
    except OSError:
        return None
    return last_title


PS_SCRIPT_BODY = r"""
# Find claude.exe whose argv contains --remote-control <SessionName> as
# adjacent tokens (avoids partial matches like "foo" vs "foo-extra").
$claudeProc = Get-CimInstance Win32_Process -Filter "Name='claude.exe'" |
    Where-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return $false }
        $tokens = $cmd -split '\s+'
        $idx = [array]::IndexOf($tokens, '--remote-control')
        ($idx -ge 0) -and ($idx + 1 -lt $tokens.Length) -and ($tokens[$idx + 1] -eq $SessionName)
    } |
    Select-Object -First 1

if (-not $claudeProc) {
    Write-Output "NOT_FOUND"
    exit 1
}

# Walk up the parent process chain to find WindowsTerminal.exe.
$proc = $claudeProc
$wtPid = $null
$walked = 0
while ($proc -and $walked -lt 8) {
    $parentId = $proc.ParentProcessId
    if (-not $parentId -or $parentId -eq 0) { break }
    try {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction Stop
    } catch { break }
    if (-not $parent) { break }
    if ($parent.Name -eq 'WindowsTerminal.exe') {
        $wtPid = [int]$parent.ProcessId
        break
    }
    $proc = $parent
    $walked++
}

if (-not $wtPid) {
    Write-Output "NO_TERMINAL"
    exit 2
}

# Bring the WT window to foreground.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class _WinAttach {
    [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr hWnd, bool fAltTab);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
}
"@

$wt = Get-Process -Id $wtPid -ErrorAction SilentlyContinue
if (-not $wt -or $wt.MainWindowHandle -eq [IntPtr]::Zero) {
    Write-Output "NO_WINDOW"
    exit 3
}

$hwnd = $wt.MainWindowHandle
# Restore if minimized (SW_RESTORE = 9), then switch to it.
if ([_WinAttach]::IsIconic($hwnd)) {
    [_WinAttach]::ShowWindow($hwnd, 9) | Out-Null
}
[_WinAttach]::SwitchToThisWindow($hwnd, $true)
Write-Output "OK $wtPid"
exit 0
"""


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("Usage: window-attach.py <session-name-or-alias>", file=sys.stderr)
        return 2

    target = sys.argv[1].strip()
    # Tolerate the slash-command "$ARGUMENTS" form where the whole arg list
    # is a single string. The session name is one token (no spaces allowed).
    target = target.split()[0]

    aliases = load_aliases()
    actual = resolve_to_actual(target, aliases)
    if actual != target:
        print(f"Resolved alias '{target}' -> '{actual}'")

    # Single-quote escape: validated names contain no quotes, but be paranoid.
    safe_name = actual.replace("'", "''")
    ps_full = f"$SessionName = '{safe_name}'\n{PS_SCRIPT_BODY}"

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_full],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"Failed to invoke PowerShell: {e}")
        return 1

    output = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    last_line = output.splitlines()[-1] if output else ""

    if last_line.startswith("OK"):
        wt_pid = last_line.split(maxsplit=1)[1] if " " in last_line else "?"
        title_id = lookup_title_for(actual) or actual
        print(f"Brought Windows Terminal to front (PID {wt_pid}).")
        print()
        print("If you see more than one tab, look for the one titled:")
        print(f"  {title_id} | <workspace-name>")
        return 0

    if last_line == "NOT_FOUND":
        print(f"No live session matches '{actual}'.")
        print("Run /window-list to see what's actually running.")
        return 1
    if last_line == "NO_TERMINAL":
        print(f"Found claude.exe for '{actual}' but its parent isn't Windows Terminal.")
        print("(Spawned outside the /window family, maybe? Attach only works for /window-* spawns.)")
        return 1
    if last_line == "NO_WINDOW":
        print(f"Found the Windows Terminal process for '{actual}' but it has no main window.")
        print("(Window may be terminating. Try again or /window-list to confirm.)")
        return 1

    print(f"Unexpected attach result. PowerShell stdout:\n{output}\n\nstderr:\n{err}")
    return result.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
