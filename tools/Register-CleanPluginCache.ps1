<#
.SYNOPSIS
    Registers (idempotently) the weekly scheduled task that runs Clean-PluginCache.ps1.

.DESCRIPTION
    Sunday 03:00, as the signed-in user with limited rights (no elevation needed), and
    catches up at the next opportunity if the computer was off. Runs the DEPLOYED copy
    in C:\Dev\claude-hooks (the repository is the source, not what runs). Re-running
    updates the task in place.

.PARAMETER ScriptPath
    The deployed Clean-PluginCache.ps1. Default C:\Dev\claude-hooks\Clean-PluginCache.ps1.

.PARAMETER TaskName
    Default 'Claude plugin-cache clean'.

.PARAMETER Unregister
    Remove the task instead.
#>
[CmdletBinding()]
param(
    [Parameter()] [string]$ScriptPath = 'C:\Dev\claude-hooks\Clean-PluginCache.ps1',
    [Parameter()] [string]$TaskName   = 'Claude plugin-cache clean',
    [Parameter()] [switch]$Unregister
)
$ErrorActionPreference = 'Stop'

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
    return
}
if (-not (Test-Path -LiteralPath $ScriptPath)) { throw "Script not found: $ScriptPath -- run deploy\Deploy-Hooks.ps1 -Apply first" }

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action    = New-ScheduledTaskAction -Execute $powershell `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
$trigger   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At ([datetime]'03:00')
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description "Deletes temp_git_* and temp_subdir_* folders older than 1 day under the Claude Code plugin cache. Source: shared-tooling\tools\Clean-PluginCache.ps1. Log: %TEMP%\plugin-cache-clean.log." | Out-Null

Write-Host "Registered '$TaskName' (Sunday 03:00, as $env:USERNAME)." -ForegroundColor Green
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo |
    Format-List @{n='TaskName';e={$TaskName}}, NextRunTime, LastRunTime, LastTaskResult
