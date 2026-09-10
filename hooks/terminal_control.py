#!/usr/bin/env python3
"""Exact operations for bridge-owned Windows Terminal topology."""
from __future__ import annotations

import os
import subprocess


class TerminalControlError(RuntimeError):
    pass


_FOCUS_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target=$env:ORCH_UIA_RUNTIME
$kind=$env:ORCH_UIA_KIND
$nodes=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
  if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
  if($kind -eq 'tab'){$node.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()}else{$node.SetFocus()}
  'OK'; exit 0
}
throw 'STALE_UIA_ELEMENT'
'''

_CLOSE_TAB_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$target=$env:ORCH_UIA_RUNTIME
$nodes=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
  if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
  $buttons=$node.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  foreach($button in $buttons){if($button.Current.Name -eq 'Close Tab'){$button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();'OK';exit 0}}
}
throw 'STALE_TAB_OR_CLOSE_BUTTON'
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
$keys=@{up=0x26;down=0x28;left=0x25;right=0x27}
if(-not $keys.ContainsKey($direction)){throw 'INVALID_RESIZE_DIRECTION'}
$previous=[ResizeNative]::GetForegroundWindow()
$nodes=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
foreach($node in $nodes){
 if((($node.GetRuntimeId()) -join '.') -ne $target){continue}
 $node.SetFocus(); Start-Sleep -Milliseconds 75
 [ResizeNative]::keybd_event(0x12,0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x10,0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event($keys[$direction],0,0,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event($keys[$direction],0,2,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x10,0,2,[UIntPtr]::Zero)
 [ResizeNative]::keybd_event(0x12,0,2,[UIntPtr]::Zero)
 if($previous -ne [IntPtr]::Zero){[ResizeNative]::SetForegroundWindow($previous)|Out-Null}
 'OK';exit 0
}
throw 'STALE_UIA_ELEMENT'
'''


def _focus(runtime_id: str, kind: str) -> None:
    env = {**os.environ, "ORCH_UIA_RUNTIME": runtime_id, "ORCH_UIA_KIND": kind}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _FOCUS_SCRIPT],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode or "OK" not in result.stdout:
        raise TerminalControlError(result.stderr.strip() or "STALE_UIA_ELEMENT")


def focus_worker(topology: dict) -> None:
    _focus(topology["tab"]["runtime_id"], "tab")
    _focus(topology["pane"]["runtime_id"], "pane")


def _wt(window_name: str, *args: str) -> None:
    result = subprocess.run(["wt.exe", "-w", window_name, *args], capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise TerminalControlError(result.stderr.strip() or "Windows Terminal command failed.")


def create_tab(window_name: str, engine: str, title: str, command: str) -> None:
    _wt(window_name, "new-tab", "--title", title, engine, "-NoExit", "-Command", command)


def split_relative(topology: dict, engine: str, title: str, command: str, direction: str = "right") -> None:
    focus_worker(topology)
    orientation = "-H" if direction in {"left", "right"} else "-V"
    _wt(topology["window_name"], "split-pane", orientation, "--title", title, engine, "-NoExit", "-Command", command)


def close_exact_pane(topology: dict) -> None:
    focus_worker(topology)
    _wt(topology["window_name"], "action", "closePane")


def close_exact_tab(topology: dict) -> None:
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["tab"]["runtime_id"]}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CLOSE_TAB_SCRIPT],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode or "OK" not in result.stdout:
        raise TerminalControlError(result.stderr.strip() or "STALE_TAB_OR_CLOSE_BUTTON")


def resize_exact_pane(topology: dict, direction: str, amount: int = 1) -> None:
    if direction not in {"up", "down", "left", "right"} or amount < 1:
        raise TerminalControlError("INVALID_RESIZE_ARGUMENT")
    env = {**os.environ, "ORCH_UIA_RUNTIME": topology["pane"]["runtime_id"],
           "ORCH_RESIZE_DIRECTION": direction}
    for _ in range(amount):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _RESIZE_SCRIPT],
                                env=env, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode or "OK" not in result.stdout:
            raise TerminalControlError(result.stderr.strip() or "RESIZE_ACTION_FAILED")


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
