#!/usr/bin/env python3
"""Windows Terminal topology bridge."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass


class TopologyError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowNode:
    bridge_id: str
    hwnd: int
    process_id: int
    runtime_id: str
    title: str
    active: bool


@dataclass(frozen=True)
class TabNode:
    bridge_id: str
    window_id: str
    runtime_id: str
    index: int
    title: str
    active: bool


@dataclass(frozen=True)
class PaneNode:
    bridge_id: str
    tab_id: str
    runtime_id: str
    index: int
    title: str
    bounds: tuple[float, float, float, float]
    certificate: str | None = None


_UIA_SCRIPT = r'''
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class TopologyNative { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }
'@
$terminalPids=@(Get-Process WindowsTerminal -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$includeInactive=__EXHAUSTIVE__
$root=[System.Windows.Automation.AutomationElement]::RootElement
$foreground=[TopologyNative]::GetForegroundWindow().ToInt64()
$windows=@()
foreach($win in $root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)) {
  if($win.Current.ProcessId -notin $terminalPids){continue}
  if($win.Current.ControlType -ne [System.Windows.Automation.ControlType]::Window){continue}
  $handle=[int64]$win.GetCurrentPropertyValue([System.Windows.Automation.AutomationElement]::NativeWindowHandleProperty)
  $tabs=$win.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)))
  $activeRuntime=$null
  foreach($candidate in $tabs){try{$candidatePattern=$candidate.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern);if($candidatePattern.Current.IsSelected){$activeRuntime=(($candidate.GetRuntimeId()) -join '.');break}}catch{}}
  $tabRows=@()
  for($i=0;$i -lt $tabs.Count;$i++){
    $tab=$tabs.Item($i); $was=$false
    try{$pat=$tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern);$was=$pat.Current.IsSelected;if(-not $was -and $includeInactive){$pat.Select();Start-Sleep -Milliseconds 75}}catch{}
    $paneRows=@()
    if($was -or $includeInactive){
      $panes=$win.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty,'TermControl')))
      for($j=0;$j -lt $panes.Count;$j++){$p=$panes.Item($j);$r=$p.Current.BoundingRectangle;$paneRows+=@{runtime=(($p.GetRuntimeId()) -join '.' );index=$j;title=$p.Current.Name;bounds=@($r.Left,$r.Top,$r.Width,$r.Height)}}
    }
    $tabRows+=@{runtime=(($tab.GetRuntimeId()) -join '.');index=$i;title=$tab.Current.Name;active=$was;panes=$paneRows}
  }
  if($includeInactive -and $activeRuntime){foreach($candidate in $tabs){if((($candidate.GetRuntimeId()) -join '.') -eq $activeRuntime){try{$restorePattern=$candidate.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern);$restorePattern.Select()}catch{};break}}}
  $windows+=@{hwnd=$handle;pid=$win.Current.ProcessId;runtime=(($win.GetRuntimeId()) -join '.');title=$win.Current.Name;active=($handle -eq $foreground);tabs=$tabRows}
}
@{windows=$windows}|ConvertTo-Json -Depth 8 -Compress
'''


def _stable(prefix: str, *parts: object) -> str:
    raw = "|".join(str(x) for x in parts).encode()
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:20]}"


def _uia_snapshot(exhaustive: bool = False) -> dict:
    if sys.platform != "win32":
        raise TopologyError("Windows Terminal topology is available only on Windows.")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _UIA_SCRIPT.replace("__EXHAUSTIVE__", "$true" if exhaustive else "$false")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode:
            raise TopologyError(result.stderr.strip() or "UI Automation query failed.")
        return json.loads(result.stdout or '{"windows":[]}')
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise TopologyError(f"Could not enumerate Windows Terminal topology: {exc}") from exc


def enumerate_topology(certificates: dict[str, str] | None = None, exhaustive: bool = False) -> dict:
    """Return bridge IDs. Certificates are pane runtime IDs mapped to tokens."""
    certificates = certificates or {}
    snapshot = _uia_snapshot(exhaustive)
    windows: list[WindowNode] = []
    tabs: list[TabNode] = []
    panes: list[PaneNode] = []
    for raw_window in snapshot.get("windows", []):
        wid = _stable("win", raw_window["pid"], raw_window["hwnd"], raw_window["runtime"])
        windows.append(WindowNode(wid, int(raw_window["hwnd"]), int(raw_window["pid"]), raw_window["runtime"], raw_window["title"], bool(raw_window["active"])))
        for raw_tab in raw_window.get("tabs", []):
            tid = _stable("tab", wid, raw_tab["runtime"])
            tabs.append(TabNode(tid, wid, raw_tab["runtime"], int(raw_tab["index"]), raw_tab["title"], bool(raw_tab["active"])))
            for raw_pane in raw_tab.get("panes", []):
                pid = _stable("pane", tid, raw_pane["runtime"])
                panes.append(PaneNode(pid, tid, raw_pane["runtime"], int(raw_pane["index"]), raw_pane["title"], tuple(raw_pane["bounds"]), certificates.get(raw_pane["runtime"])))
    return {"windows": [asdict(x) for x in windows], "tabs": [asdict(x) for x in tabs], "panes": [asdict(x) for x in panes]}


def resolve_pane(topology: dict, pane_id: str) -> dict:
    for pane in topology.get("panes", []):
        if pane["bridge_id"] == pane_id:
            return pane
    raise TopologyError(f"STALE_PANE: {pane_id} no longer exists.")


def verify_binding(pane: dict, expected_certificate: str, agent_ref: dict) -> bool:
    """Certificate plus V1 PID/start/image identity; never a title alone."""
    if not expected_certificate or pane.get("certificate") != expected_certificate:
        return False
    return bool(agent_ref.get("pid") and agent_ref.get("process_start_time") and agent_ref.get("process_image"))


def bind_certificate(topology: dict, certificate: str, agent_ref: dict, console_screen: str) -> dict:
    """Bind a PID-targeted console to exactly one UIA pane.

    The certificate must appear in the target console and exactly one terminal
    control. This is a two-channel proof, not a title-only association.
    """
    if not certificate or certificate not in console_screen:
        raise TopologyError("BINDING_UNPROVEN: certificate is absent from the target console.")
    matches = [pane for pane in topology.get("panes", []) if pane.get("title") == certificate]
    if len(matches) != 1:
        raise TopologyError(f"BINDING_UNPROVEN: certificate resolves to {len(matches)} panes.")
    pane = {**matches[0], "certificate": certificate}
    if not verify_binding(pane, certificate, agent_ref):
        raise TopologyError("BINDING_UNPROVEN: target process identity is incomplete.")
    return pane
