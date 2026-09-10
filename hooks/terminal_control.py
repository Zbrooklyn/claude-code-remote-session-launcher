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
    _focus(topology["tab"]["runtime_id"], "tab")
    _wt(topology["window_name"], "action", "closeTab")


def resize_exact_pane(topology: dict, direction: str, amount: int = 1) -> None:
    focus_worker(topology)
    _wt(topology["window_name"], "action", "resizePane", "--direction", direction, "--size", str(amount))


def read_scrollback(topology: dict) -> str:
    raise TerminalControlError("NOT_EXPOSED: attributed UIA TextPattern scrollback is unavailable on this Windows Terminal build.")
