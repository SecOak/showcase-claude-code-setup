<#
.SYNOPSIS
    The hourly job: back up the Claude home to OneDrive, then mirror the portable
    config into this repository and commit it. Called by the scheduled task.

.DESCRIPTION
    Runs Backup-ClaudeToOneDrive.ps1 and then Sync-ClaudeSeat.ps1 -Commit. The
    commit is local only; pushing stays a manual step (or pass -Push here and
    re-register the task if you decide the laptop should receive commits without you).
    Exit code is the highest of the two scripts.

    The task launches this through conhost --headless, which always reports exit
    code 0 to Task Scheduler. So failures are surfaced here instead: a Windows toast
    notification, and logs\claudeseat-last-status.txt (one line: OK or FAILED, the
    time, and the log path).

.PARAMETER Push
    Also push the commit.
#>
[CmdletBinding()]
param([Parameter()] [switch]$Push)

$ErrorActionPreference = 'Continue'
# The task inherits the environment from the last sign-in; tools installed since then
# (git, node, npm, claude) are missing from it until PATH is reloaded from the registry.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$here = $PSScriptRoot
$logDir = 'C:\ProgramData\DevBackup\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("claudeseat-hourly-" + (Get-Date -Format 'yyyy-MM-dd-HHmmss') + ".log")
$statusFile = Join-Path $logDir 'claudeseat-last-status.txt'

function Show-FailureToast { param([string]$Text)
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $safe = [System.Security.SecurityElement]::Escape($Text)
        $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>ClaudeSeat hourly job failed</text><text>$safe</text></binding></visual></toast>")
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        # Any registered application id works for a toast from a script; Windows PowerShell's own.
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($toast)
    } catch {
        Add-Content -LiteralPath $log -Value ("toast failed: " + $_.Exception.Message) -Encoding Ascii
    }
}

# Each child runs inside try/catch so a terminating error is logged and counted as a
# failure instead of silently ending this script before the status line is written.
$backupCode = 1
try {
    & (Join-Path $here 'Backup-ClaudeToOneDrive.ps1') *>> $log
    $backupCode = $LASTEXITCODE
} catch {
    Add-Content -LiteralPath $log -Value ("backup threw: " + $_.Exception.Message) -Encoding Ascii
}

$syncCode = 1
try {
    $syncArgs = @{ Commit = $true }
    if ($Push) { $syncArgs.Push = $true }
    & (Join-Path $here 'Sync-ClaudeSeat.ps1') @syncArgs *>> $log
    $syncCode = $LASTEXITCODE
} catch {
    Add-Content -LiteralPath $log -Value ("sync threw: " + $_.Exception.Message) -Encoding Ascii
}

$exitCode = [Math]::Max([int]$backupCode, [int]$syncCode)
$summary = "hourly finished: backup exit {0}, sync exit {1}" -f $backupCode, $syncCode
Add-Content -LiteralPath $log -Value $summary -Encoding Ascii

$state = if ($exitCode -eq 0) { 'OK' } else { 'FAILED' }
[System.IO.File]::WriteAllText($statusFile, ("{0} {1} {2}`n" -f $state, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $log), (New-Object System.Text.UTF8Encoding($false)))
if ($exitCode -ne 0) { Show-FailureToast ("backup exit $backupCode, sync exit $syncCode. Log: $log") }

# Prune this wrapper's own logs after 30 days.
Get-ChildItem -LiteralPath $logDir -Filter 'claudeseat-hourly-*.log' -File |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $logDir -Filter 'claudeseat-sync-*.log' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force -ErrorAction SilentlyContinue

exit $exitCode
