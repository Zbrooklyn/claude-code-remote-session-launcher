#Requires -Version 7
# install.ps1 — Claude Code Remote Session Launcher installer
#
# Copies the slash commands and hook scripts into ~/.claude/.
# Does not overwrite an existing window-config.json.
#
# Requires PowerShell 7+ (pwsh.exe). Under Windows PowerShell 5.1
# (powershell.exe) this script silently no-ops; the #Requires line
# above forces a clear error instead. If you only have 5.1, install
# PowerShell 7 from https://github.com/PowerShell/PowerShell/releases
# or run via WSL.

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$claudeDir = Join-Path $HOME ".claude"
$cmdsDir = Join-Path $claudeDir "commands"
$hooksDir = Join-Path $claudeDir "hooks"

Write-Host "Claude Code Remote Session Launcher — installer"
Write-Host "Source: $repoRoot"
Write-Host "Target: $claudeDir"
Write-Host ""

# Sanity checks
if (-not (Test-Path $claudeDir)) {
    Write-Host "ERROR: $claudeDir does not exist. Is Claude Code installed?" -ForegroundColor Red
    exit 1
}

# Ensure subdirs exist
New-Item -ItemType Directory -Force -Path $cmdsDir | Out-Null
New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

# Copy command files
$cmdFiles = Get-ChildItem -Path (Join-Path $repoRoot "commands") -Filter "*.md"
foreach ($f in $cmdFiles) {
    $dest = Join-Path $cmdsDir $f.Name
    Copy-Item -Path $f.FullName -Destination $dest -Force
    Write-Host "  copied command: $($f.Name)"
}

# Copy hook files
$hookFiles = Get-ChildItem -Path (Join-Path $repoRoot "hooks") -Filter "*.py"
foreach ($f in $hookFiles) {
    $dest = Join-Path $hooksDir $f.Name
    Copy-Item -Path $f.FullName -Destination $dest -Force
    Write-Host "  copied hook:    $($f.Name)"
}

# Config template — only place if no config exists
$configDest = Join-Path $claudeDir "window-config.json"
$configTemplate = Join-Path $repoRoot "window-config.template.json"
if (-not (Test-Path $configDest)) {
    if (Test-Path $configTemplate) {
        Write-Host ""
        Write-Host "No existing window-config.json found." -ForegroundColor Yellow
        Write-Host "Run /window-setup inside Claude Code to generate yours interactively,"
        Write-Host "or copy $configTemplate to $configDest and edit by hand."
    }
} else {
    Write-Host ""
    Write-Host "Existing window-config.json preserved at $configDest" -ForegroundColor Green
}

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "Next step: open Claude Code and run /window-setup."
