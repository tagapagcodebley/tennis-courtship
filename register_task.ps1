# Registers a Windows Scheduled Task that runs run_watcher.ps1 every 30
# minutes, indefinitely. Run this once (in an elevated or normal
# PowerShell prompt -- elevation not required for a per-user task).

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$taskName = "TennisCourtWatcher"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptDir\run_watcher.ps1`"" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
# Leaving Repetition.Duration unset (rather than [TimeSpan]::MaxValue, which
# Register-ScheduledTask fails to serialize -- "P99999999DT23H59M59S" is out
# of the accepted XML duration range) means "repeat every 30 min, no end".
$trigger.Repetition.Duration = ""
$trigger.Repetition.StopAtDurationEnd = $false

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Checks Princes Gardens tennis court availability every 30 min." `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Error "Failed to register scheduled task: $_"
    exit 1
}

Write-Host "Registered scheduled task '$taskName'. It will run every 30 minutes."
Write-Host "View/manage it with: Get-ScheduledTask -TaskName $taskName"
Write-Host "Run it immediately with: Start-ScheduledTask -TaskName $taskName"
Write-Host "Remove it with: Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
