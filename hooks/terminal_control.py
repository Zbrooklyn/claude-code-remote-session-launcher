#!/usr/bin/env python3
"""Exact operations for bridge-owned Windows Terminal topology."""
from __future__ import annotations

import ctypes
import os
import subprocess
import time

from terminal_topology import enumerate_topology


class TerminalControlError(RuntimeError):
    pass


_FOCUS_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target=$env:ORCH_UIA_RUNTIME
$kind=$env:ORCH_UIA_KIND
$handle=[int64]$env:ORCH_UIA_HWND
$scope=[System.Windows.Automation.AutomationElement]::RootElement
if($handle -ne 0){
 try {$scope=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)} catch {throw 'STALE_UIA_WINDOW'}
 if(-not $scope){throw 'STALE_UIA_WINDOW'}
}
$nodes=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
  if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
  if($kind -eq 'tab'){$node.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()}else{$node.SetFocus()}
  'OK'; exit 0
}
throw 'STALE_UIA_ELEMENT'
'''

_FOREGROUND_WINDOW_SCRIPT = r'''
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class ForegroundNative { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }
'@
[ForegroundNative]::GetForegroundWindow().ToInt64()
'''

_RESTORE_FOREGROUND_SCRIPT = r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class ForegroundRestoreNative {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern void SwitchToThisWindow(IntPtr h, bool altTab);
 [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int nCmdShow);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p);
 [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
 [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
}
'@
$target=[IntPtr]([int64]$env:ORCH_PREVIOUS_FOREGROUND)
$targetThread=[ForegroundRestoreNative]::GetWindowThreadProcessId($target,[IntPtr]::Zero)
$currentThread=[ForegroundRestoreNative]::GetCurrentThreadId()
$foreground=[ForegroundRestoreNative]::GetForegroundWindow()
$foregroundThread=[ForegroundRestoreNative]::GetWindowThreadProcessId($foreground,[IntPtr]::Zero)
$attached=@()
foreach($pair in @(@($currentThread,$targetThread),@($currentThread,$foregroundThread),@($foregroundThread,$targetThread))){
 if($pair[0] -ne 0 -and $pair[1] -ne 0 -and $pair[0] -ne $pair[1] -and [ForegroundRestoreNative]::AttachThreadInput($pair[0],$pair[1],$true)){$attached+=,$pair}
}
try {
 [ForegroundRestoreNative]::ShowWindow($target,9)|Out-Null
 try { [System.Windows.Automation.AutomationElement]::FromHandle($target).SetFocus() } catch {}
 [ForegroundRestoreNative]::BringWindowToTop($target)|Out-Null
 [ForegroundRestoreNative]::SetForegroundWindow($target)|Out-Null
 [ForegroundRestoreNative]::SwitchToThisWindow($target,$true)
 try { [System.Windows.Automation.AutomationElement]::FromHandle($target).SetFocus() } catch {}
 [ForegroundRestoreNative]::GetForegroundWindow().ToInt64()
} finally { foreach($pair in $attached){[ForegroundRestoreNative]::AttachThreadInput($pair[0],$pair[1],$false)|Out-Null} }
'''

_CLOSE_TAB_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target=$env:ORCH_UIA_RUNTIME
$handle=[int64]$env:ORCH_UIA_HWND
$scope=[System.Windows.Automation.AutomationElement]::RootElement
if($handle -ne 0){try {$scope=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)} catch {throw 'STALE_UIA_WINDOW'}}
$nodes=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
  if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
  $buttons=$node.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($button in $buttons){if($button.Current.Name -eq 'Close Tab'){$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();'OK';exit 0}}
}
throw 'STALE_TAB_OR_CLOSE_BUTTON'
'''

_CLOSE_PANE_HOTKEY_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class PaneCloseNative {
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags,uint dx,uint dy,uint data,UIntPtr extra);
 [DllImport("user32.dll")] public static extern void keybd_event(byte v,byte s,uint f,UIntPtr e);
}
'@
$target=$env:ORCH_UIA_RUNTIME
$certificate=$env:ORCH_UIA_CERTIFICATE
$handle=[int64]$env:ORCH_UIA_HWND
$previous=[PaneCloseNative]::GetForegroundWindow(); $cursor=New-Object PaneCloseNative+POINT
[PaneCloseNative]::GetCursorPos([ref]$cursor)|Out-Null
$scope=[System.Windows.Automation.AutomationElement]::RootElement
if($handle -ne 0){try {$scope=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)} catch {throw 'STALE_UIA_WINDOW'}}
$nodes=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$matches=@()
foreach($node in $nodes){
 if($node.Current.ClassName -ne 'TermControl'){continue}
 $runtime=(($node.GetRuntimeId()) -join '.')
 if($runtime -ne $target -and (-not $certificate -or $node.Current.Name -ne $certificate)){continue}
 $matches+=$node
}
if($matches.Count -ne 1){throw 'STALE_UIA_ELEMENT'}
foreach($node in $matches){
 $r=$node.Current.BoundingRectangle
 if($r.Width -le 1 -or $r.Height -le 1){throw 'INVALID_PANE_BOUNDS'}
 $node.SetFocus(); Start-Sleep -Milliseconds 75
 [PaneCloseNative]::SetCursorPos([int]($r.Left+$r.Width/2),[int]($r.Top+$r.Height/2))|Out-Null
 [PaneCloseNative]::mouse_event(0x2,0,0,0,[UIntPtr]::Zero); [PaneCloseNative]::mouse_event(0x4,0,0,0,[UIntPtr]::Zero)
 Start-Sleep -Milliseconds 50
 [PaneCloseNative]::keybd_event(0x11,0,0,[UIntPtr]::Zero); [PaneCloseNative]::keybd_event(0x10,0,0,[UIntPtr]::Zero); [PaneCloseNative]::keybd_event(0x57,0,0,[UIntPtr]::Zero)
 [PaneCloseNative]::keybd_event(0x57,0,2,[UIntPtr]::Zero); [PaneCloseNative]::keybd_event(0x10,0,2,[UIntPtr]::Zero); [PaneCloseNative]::keybd_event(0x11,0,2,[UIntPtr]::Zero)
 [PaneCloseNative]::SetCursorPos($cursor.X,$cursor.Y)|Out-Null
 if($previous -ne [IntPtr]::Zero){[PaneCloseNative]::SetForegroundWindow($previous)|Out-Null}
 'OK';exit 0
}
throw 'STALE_UIA_ELEMENT'
'''

_SCROLLBACK_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target=$env:ORCH_UIA_RUNTIME
$nodes=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
  if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
  try {
    $pattern=$node.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
    [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
    [Console]::Write($pattern.DocumentRange.GetText(-1))
    exit 0
  } catch { throw 'TEXT_PATTERN_NOT_EXPOSED' }
}
throw 'STALE_UIA_ELEMENT'
'''

_RESIZE_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class ResizeNative {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern void keybd_event(byte v,byte s,uint f,UIntPtr e);
}
'@
$target=$env:ORCH_UIA_RUNTIME; $direction=$env:ORCH_RESIZE_DIRECTION
$certificate=$env:ORCH_UIA_CERTIFICATE; $handle=[int64]$env:ORCH_UIA_HWND
$count=[int]$env:ORCH_RESIZE_COUNT
$keys=@{up=0x26;down=0x28;left=0x25;right=0x27}
if(-not $keys.ContainsKey($direction)){throw 'INVALID_RESIZE_DIRECTION'}
$previous=[ResizeNative]::GetForegroundWindow()
$scope=[System.Windows.Automation.AutomationElement]::RootElement
if($handle -ne 0){try {$scope=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)} catch {throw 'STALE_UIA_WINDOW'}}
if(-not $scope){throw 'STALE_UIA_WINDOW'}
$nodes=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$matches=@()
foreach($node in $nodes){
 if($node.Current.ClassName -ne 'TermControl'){continue}
 $runtime=(($node.GetRuntimeId()) -join '.')
 if($runtime -ne $target -and (-not $certificate -or $node.Current.Name -ne $certificate)){continue}
 $matches+=$node
}
if($matches.Count -ne 1){throw 'STALE_UIA_ELEMENT'}
$node=$matches[0]
$node.SetFocus(); Start-Sleep -Milliseconds 75
for($i=0;$i -lt $count;$i++){
 [ResizeNative]::keybd_event(0x12,0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x10,0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event($keys[$direction],0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event($keys[$direction],0,2,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x10,0,2,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x12,0,2,[UIntPtr]::Zero)
}
if($previous -ne [IntPtr]::Zero){[ResizeNative]::SetForegroundWindow($previous)|Out-Null}
'OK';exit 0
'''


def _focus(runtime_id: str, kind: str, hwnd: int | None = None) -> None:
    env = {**os.environ, "ORCH_UIA_RUNTIME": runtime_id, "ORCH_UIA_KIND": kind,
           "ORCH_UIA_HWND": str(hwnd or 0)}
    # Windows Terminal can invalidate UIA descendants while it is creating a
    # tab or changing focus.  Re-run the exact RuntimeId lookup from the root;
    # never substitute a title, index, or nearest pane on retry.
    last_error = "STALE_UIA_ELEMENT"
    for attempt in range(4):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _FOCUS_SCRIPT],
                                env=env, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode == 0 and "OK" in result.stdout:
            return
        last_error = result.stderr.strip() or last_error
        if attempt < 3:
            time.sleep(0.15)
    raise TerminalControlError(last_error)


def _foreground_window() -> int | None:
    """Best-effort foreground capture; inability to observe must not strand a worker."""
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _FOREGROUND_WINDOW_SCRIPT],
                                capture_output=True, text=True, timeout=10, check=False)
        return int(result.stdout.strip()) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _restore_foreground(hwnd: int | None) -> None:
    if not hwnd:
        return
    for _ in range(3):
        try:
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _RESTORE_FOREGROUND_SCRIPT],
                                    env={**os.environ, "ORCH_PREVIOUS_FOREGROUND": str(hwnd)},
                                    capture_output=True, text=True, timeout=10, check=False)
            if result.returncode == 0 and result.stdout.strip() == str(hwnd):
                return
            time.sleep(0.1)
        except (OSError, subprocess.SubprocessError):
            return


def _with_worker_focus(topology: dict, action) -> None:
    previous = _foreground_window()
    try:
        focus_worker(topology)
        action()
    finally:
        _restore_foreground(previous)


def focus_worker(topology: dict) -> None:
    hwnd = topology.get("window", {}).get("hwnd")
    _focus(topology["tab"]["runtime_id"], "tab", hwnd)
    _focus(topology["pane"]["runtime_id"], "pane", hwnd)


def _wt(window_name: str, *args: str) -> None:
    result = subprocess.run(["wt.exe", "-w", window_name, *args], capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise TerminalControlError(result.stderr.strip() or "Windows Terminal command failed.")


def ensure_window_area(hwnd: int, width: int = 1500, height: int = 1000) -> bool:
    """Grow a bridge-owned Terminal window to a workable size without stealing focus.

    A crowded worker grid (2x2 for four workers, 2x3 for six) in a default-sized
    window produces panes only one text row tall, and a one-row console cannot
    run and echo a command.  This resizes only a window the caller owns, and
    uses SWP_NOACTIVATE / SWP_NOZORDER so it neither maximizes to fullscreen nor
    grabs the foreground away from the user.  It only ever grows the window.
    """
    if not hwnd or os.name != "nt":
        return False
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        return False
    target_w = max(width, rect.right - rect.left)
    target_h = max(height, rect.bottom - rect.top)
    SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0002, 0x0004, 0x0010
    return bool(user32.SetWindowPos(int(hwnd), 0, 0, 0, target_w, target_h,
                                    SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE))


def maximize_window(hwnd: int) -> bool:
    """Deprecated in favour of ensure_window_area; kept as a fallback lever."""
    if not hwnd or os.name != "nt":
        return False
    return bool(ctypes.windll.user32.ShowWindow(int(hwnd), 3))  # SW_MAXIMIZE


def create_tab(window_name: str, engine: str, title: str, command: str) -> None:
    _wt(window_name, "new-tab", "--title", title, engine, "-NoExit", "-Command", command)


def split_relative(topology: dict, engine: str, title: str, command: str, direction: str = "right",
                   size: float | None = None, cwd: str | None = None) -> None:
    orientation = "-H" if direction in {"left", "right"} else "-V"
    args = ["split-pane", orientation]
    if size is not None:
        args.extend(("--size", str(size)))
    if cwd:
        args.extend(("-d", cwd))
    args.extend(("--title", title, engine, "-NoExit", "-Command", command))
    _with_worker_focus(topology, lambda: _wt(topology["window_name"], *args))


def _close_pane_hotkey(topology: dict) -> None:
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["pane"]["runtime_id"],
           "ORCH_UIA_CERTIFICATE": topology.get("certificate") or "",
           "ORCH_UIA_HWND": str(topology.get("window", {}).get("hwnd") or 0)}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CLOSE_PANE_HOTKEY_SCRIPT],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode or "OK" not in result.stdout:
        raise TerminalControlError(result.stderr.strip() or "PANE_HOTKEY_FAILED")


def _closure_target(topology: dict, snapshot: dict) -> dict | None:
    """Re-resolve a redrawn owned pane without falling back to position/title alone."""
    original = topology["pane"]["runtime_id"]
    for pane in snapshot["panes"]:
        if pane["runtime_id"] == original:
            return topology
    certificate = topology.get("certificate")
    candidates = [pane for pane in snapshot["panes"] if certificate and pane.get("title") == certificate]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise TerminalControlError("PANE_CLOSE_AMBIGUOUS_REDRAW")
    return {**topology, "pane": candidates[0]}


def close_pane_and_verify(topology: dict) -> None:
    """Close one certified pane only when its exact UIA runtime ID disappears.

    Windows Terminal has no ``action`` CLI subcommand: ``wt -w <id> action
    closePane`` is parsed as ``new-tab action closePane`` and opens a stray tab
    with a launch error, which also hides the target pane from UIA.  The only
    trusted mechanism is the pane-scoped close hotkey below.
    """
    hwnd = topology["window"]["hwnd"]
    snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd])
    current = _closure_target(topology, snapshot)
    if current is None:
        return
    for attempt in range(8):
        try:
            _close_pane_hotkey(current)
            break
        except TerminalControlError as exc:
            if "STALE_UIA_ELEMENT" not in str(exc) or attempt == 7:
                raise
            time.sleep(0.5)
            snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd])
            current = _closure_target(topology, snapshot)
            if current is None:
                return
    time.sleep(0.25)
    snapshot = enumerate_topology(exhaustive=True, hwnds=[hwnd])
    if _closure_target(topology, snapshot) is not None:
        raise TerminalControlError("PANE_CLOSE_UNPROVEN")


def close_exact_tab(topology: dict) -> None:
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["tab"]["runtime_id"],
           "ORCH_UIA_HWND": str(topology.get("window", {}).get("hwnd") or 0)}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CLOSE_TAB_SCRIPT],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode or "OK" not in result.stdout:
        raise TerminalControlError(result.stderr.strip() or "STALE_TAB_OR_CLOSE_BUTTON")


def resize_exact_pane(topology: dict, direction: str, amount: int = 1) -> None:
    if direction not in {"up", "down", "left", "right"} or amount < 1:
        raise TerminalControlError("INVALID_RESIZE_ARGUMENT")
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["pane"]["runtime_id"],
           "ORCH_UIA_CERTIFICATE": topology.get("certificate") or "",
           "ORCH_UIA_HWND": str(topology.get("window", {}).get("hwnd") or 0),
           "ORCH_RESIZE_DIRECTION": direction, "ORCH_RESIZE_COUNT": str(amount)}
    last_error = "RESIZE_ACTION_FAILED"
    for attempt in range(4):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _RESIZE_SCRIPT],
                                env=env, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode == 0 and "OK" in result.stdout:
            return
        last_error = result.stderr.strip() or last_error
        if "STALE_UIA_" not in last_error or attempt == 3:
            break
        time.sleep(0.15)
    raise TerminalControlError(last_error)


def read_scrollback(topology: dict) -> str:
    """Read the TextPattern belonging to this already-certified pane.

    RuntimeId is re-resolved by the worker bridge before this call.  The
    certificate/PID binding is the attribution proof; TextPattern alone is not.
    """
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["pane"]["runtime_id"]}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SCROLLBACK_SCRIPT],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise TerminalControlError(result.stderr.strip() or "TEXT_PATTERN_NOT_EXPOSED")
    return result.stdout
