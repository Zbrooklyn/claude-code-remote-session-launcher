# Disposable Ctrl+C acceptance. Never resolves a generic PID: the target must
# retain this exact unique launch marker before native input is attempted.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$agentctl = Join-Path $root 'hooks\agentctl.py'
$targetPid = $null
try {
    $marker = "V1_INTERRUPT_$([guid]::NewGuid().ToString('N'))"
    Start-Process wt.exe -ArgumentList @('-w','new','new-tab','--title',$marker,'powershell.exe','-NoExit','-Command',"Write-Output '$marker'") | Out-Null
    for ($i=0; $i -lt 80; $i++) {
        $candidate = Get-CimInstance Win32_Process | Where-Object {
            $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$marker*"
        } | Select-Object -First 1
        if ($candidate) { $targetPid = [int]$candidate.ProcessId; break }
        Start-Sleep -Milliseconds 100
    }
    if (-not $targetPid) { throw 'Disposable interrupt target never appeared.' }
    $check = Get-CimInstance Win32_Process -Filter "ProcessId=$targetPid"
    if ($check.CommandLine -notlike "*$marker*") { throw 'Refusing target whose marker changed.' }
    & py $agentctl send "$targetPid" 'Start-Sleep -Seconds 30' --enter --timeout 1 --json | Out-Null
    & py $agentctl interrupt "$targetPid" --json | Out-Null
    Start-Sleep -Milliseconds 300
    $screen = (& py $agentctl read "$targetPid" --json | ConvertFrom-Json).screen
    if ($screen -notmatch 'PS .*>') { throw 'No PowerShell prompt after Ctrl+C.' }
    if (-not (Get-Process -Id $targetPid -ErrorAction SilentlyContinue)) { throw 'Ctrl+C killed PowerShell.' }
    [pscustomobject]@{status='PASS';targetPid=$targetPid;marker=$marker;targetAlive=$true}|ConvertTo-Json -Compress
}
finally {
    if ($targetPid) { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue }
}
