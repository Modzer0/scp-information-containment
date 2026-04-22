# SCP: Information Containment — Windows PowerShell installer
# Creates .venv, installs dependencies, verifies the install.

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoDir   = Split-Path -Parent $scriptDir
Set-Location $repoDir

# ---- find a usable Python ---------------------------------------------
function Find-Python {
    foreach ($cand in 'py', 'python3.14', 'python3.13', 'python3.12', 'python3.11', 'python3', 'python') {
        $exe = Get-Command $cand -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args = @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)')
        # 'py' launcher needs an explicit version hint to pick 3.11+
        if ($cand -eq 'py') {
            & $exe -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>$null
        } else {
            & $exe @args 2>$null
        }
        if ($LASTEXITCODE -eq 0) {
            if ($cand -eq 'py') { return @('py', '-3') }
            return @($cand)
        }
    }
    return $null
}

$pythonCmd = Find-Python
if (-not $pythonCmd) {
    Write-Host "error: Python 3.11+ not found on PATH" -ForegroundColor Red
    Write-Host "       install from https://www.python.org/downloads/"
    exit 1
}
Write-Host "using: $($pythonCmd -join ' ')"
& $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)] + '--version')

# ---- venv -------------------------------------------------------------
if (-not (Test-Path '.venv')) {
    Write-Host "creating virtual env at .venv/"
    & $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)] + @('-m', 'venv', '.venv'))
} else {
    Write-Host "reusing existing .venv/"
}

$venvPy = Join-Path $repoDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "error: venv python not found at $venvPy" -ForegroundColor Red
    exit 1
}

# ---- install ----------------------------------------------------------
Write-Host "upgrading pip..."
& $venvPy -m pip install --upgrade --quiet pip

Write-Host "installing scp-information-containment (editable)..."
& $venvPy -m pip install -e . --quiet

# ---- verify -----------------------------------------------------------
Write-Host "verifying imports..."
& $venvPy -c "from scp.daemon.main import Daemon; from scp.tui.main import ScpTui; print('ok')"

Write-Host ""
Write-Host "install complete." -ForegroundColor Green
Write-Host "next steps:"
Write-Host "  1) start the daemon:     .\scripts\run-daemon.ps1"
Write-Host "  2) in another terminal:  .\scripts\run-tui.ps1"
Write-Host "  3) inside the TUI type:  help"
