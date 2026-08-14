# Wrapper invoked by the scheduled task. Loads secrets.ps1 (Gmail creds)
# into the environment, then runs a single check with watch_courts.py.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$secretsPath = Join-Path $PSScriptRoot "secrets.ps1"
if (Test-Path $secretsPath) {
    . $secretsPath
} else {
    Write-Error "secrets.ps1 not found. Copy secrets.example.ps1 to secrets.ps1 and fill in your Gmail App Password."
    exit 1
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython (Join-Path $PSScriptRoot "watch_courts.py")
} else {
    python (Join-Path $PSScriptRoot "watch_courts.py")
}
