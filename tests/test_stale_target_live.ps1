# Proves a captured process identity cannot silently fall through to a later PID.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$agentctl = Join-Path $root 'hooks\agentctl.py'
$targetPid = $null
try {
    $marker = "V1_STALE_$([guid]::NewGuid().ToString('N'))"
    Start-Process wt.exe -ArgumentList @('-w','new','new-tab','--title',$marker,'powershell.exe','-NoExit','-Command',"Write-Output '$marker'") | Out-Null
    for ($i=0; $i -lt 80; $i++) {
        $candidate = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$marker*" } | Select-Object -First 1
        if ($candidate) { $targetPid = [int]$candidate.ProcessId; break }
        Start-Sleep -Milliseconds 100
    }
    if (-not $targetPid) { throw 'Disposable stale-target probe did not start.' }
    $identity = (& py $agentctl inspect "$targetPid" --json | ConvertFrom-Json).target
    Stop-Process -Id $targetPid -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 150
    $raw = & py $agentctl read "$targetPid" --expect-start-time $identity.process_start_time --json
    if ($LASTEXITCODE -eq 0) { throw 'A stopped target was accepted.' }
    $result = $raw | ConvertFrom-Json
    if ($result.code -ne 'STALE_TARGET') { throw "Expected STALE_TARGET, got $($result.code)." }
    [pscustomobject]@{status='PASS';targetPid=$targetPid;code=$result.code}|ConvertTo-Json -Compress
}
finally {
    if ($targetPid) { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue }
}
