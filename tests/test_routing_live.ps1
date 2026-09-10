# Requires Windows Terminal, Python, Windows PowerShell 5.1, and PowerShell 7.
# Disposable end-to-end acceptance: two unfocused workers, ten isolated cycles,
# target read-back, then Ctrl+C safety.  It always stops the probe processes.
[CmdletBinding()]
param([int] $Cycles = 10, [switch] $SkipInterrupt)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$agentctl = Join-Path $root 'hooks\agentctl.py'
$created = @()

if (-not ('V1Window' -as [type])) {
    Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class V1Window {
  delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int command);
  public static bool MinimizeContaining(string text) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { var s = new StringBuilder(512); GetWindowText(h,s,s.Capacity);
      if (IsWindowVisible(h) && s.ToString().IndexOf(text, StringComparison.OrdinalIgnoreCase) >= 0) { found=h; return false; }
      return true; }, IntPtr.Zero);
    return found != IntPtr.Zero && ShowWindow(found, 6);
  }
}
'@
}

function Invoke-AgentctlJson([string[]] $Arguments) {
    $raw = & py $agentctl @Arguments
    if ($LASTEXITCODE -ne 0) { throw "agentctl failed: $raw" }
    return $raw | ConvertFrom-Json
}

function Start-DisposableWorker([string] $Engine, [string] $Name) {
    $ready = "V1_READY_${Name}_$([guid]::NewGuid().ToString('N'))"
    $command = "Write-Output '$ready'; `$Host.UI.RawUI.WindowTitle='$Name'"
    Start-Process wt.exe -ArgumentList @('-w', 'new', 'new-tab', '--title', $Name, $Engine, '-NoExit', '-Command', $command) | Out-Null
    for ($i = 0; $i -lt 80; $i++) {
        $p = Get-CimInstance Win32_Process | Where-Object {
            $_.Name -eq (Split-Path $Engine -Leaf) -and $_.CommandLine -like "*$ready*"
        } | Select-Object -First 1
        if ($p) {
            $script:created += [int]$p.ProcessId
            $probe = Invoke-AgentctlJson @('read', "$($p.ProcessId)", '--json')
            if ($probe.screen -like "*$ready*") { return [int]$p.ProcessId }
        }
        Start-Sleep -Milliseconds 150
    }
    throw "Timed out waiting for $Engine disposable worker."
}

try {
    $a = Start-DisposableWorker 'powershell.exe' 'agentctl-v1-a'
    $b = Start-DisposableWorker 'pwsh.exe' 'agentctl-v1-b'

    if (-not [V1Window]::MinimizeContaining('agentctl-v1-b')) { throw 'Could not minimize the exact worker B Terminal window.' }

    # Make another application foreground. Native console I/O must not depend on Terminal focus.
    $notepad = Start-Process notepad.exe -PassThru
    Start-Sleep -Milliseconds 300

    for ($i = 1; $i -le $Cycles; $i++) {
        $ma = "V1_A_${i}_$([guid]::NewGuid().ToString('N'))"
        $mb = "V1_B_${i}_$([guid]::NewGuid().ToString('N'))"
        $ra = Invoke-AgentctlJson @('send', "$a", "Write-Output '$ma'", '--enter', '--verify', $ma, '--timeout', '5', '--json')
        $rb = Invoke-AgentctlJson @('send', "$b", "Write-Output '$mb'", '--enter', '--verify', $mb, '--timeout', '5', '--json')
        if ($ra.phase -ne 'COMMAND_EXECUTED' -or $rb.phase -ne 'COMMAND_EXECUTED') { throw "Cycle $i did not execute both commands." }
        $sa = (Invoke-AgentctlJson @('read', "$a", '--json')).screen
        $sb = (Invoke-AgentctlJson @('read', "$b", '--json')).screen
        if ($sa -notlike "*$ma*" -or $sa -like "*$mb*" -or $sb -notlike "*$mb*" -or $sb -like "*$ma*") {
            throw "Cross-session routing failure in cycle $i."
        }
    }

    if (-not $SkipInterrupt) {
        # Interrupt a single running command. The helper refuses a console with an
        # unrelated member before delivering the console-scoped control event.
        Invoke-AgentctlJson @('send', "$a", 'Start-Sleep -Seconds 30', '--enter', '--timeout', '1', '--json') | Out-Null
        Start-Sleep -Milliseconds 200
        $interrupted = Invoke-AgentctlJson @('interrupt', "$a", '--json')
        if ($interrupted.phase -ne 'INTERRUPT_DELIVERED') { throw 'Interrupt was not delivered.' }
        Start-Sleep -Milliseconds 300
        $afterInterrupt = Invoke-AgentctlJson @('read', "$a", '--json')
        if ($afterInterrupt.screen -notmatch 'PS .*>') { throw 'PowerShell did not return to a prompt after Ctrl+C.' }
        if (-not (Get-Process -Id $a -ErrorAction SilentlyContinue)) { throw 'Ctrl+C killed the target shell.' }
    }

    [pscustomobject]@{ status='PASS'; cycles=$Cycles; workerA=$a; workerB=$b; focus='notepad'; minimized='worker B'; engines='powershell.exe,pwsh.exe' } | ConvertTo-Json -Compress
}
finally {
    foreach ($workerPid in @($script:created | Select-Object -Unique)) {
        Stop-Process -Id $workerPid -Force -ErrorAction SilentlyContinue
    }
    if ($notepad) { Stop-Process -Id $notepad.Id -Force -ErrorAction SilentlyContinue }
}
