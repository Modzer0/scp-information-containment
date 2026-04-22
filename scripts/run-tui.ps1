# Attach the TUI to a running SCP daemon.
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoDir   = Split-Path -Parent $scriptDir
Set-Location $repoDir

$venvPy = Join-Path $repoDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "error: .venv not found. run .\scripts\install.ps1 first." -ForegroundColor Red
    exit 1
}

& $venvPy -m scp tui
