<#
.SYNOPSIS
    Registers (or re-registers) the hourly "ClaudeSeat Backup to OneDrive" scheduled
    task for the signed-in user on this machine.

.DESCRIPTION
    The task runs scripts\Invoke-ClaudeSeatHourly.ps1 from this repository every hour
    at :45, through conhost --headless so no
    window flashes. It runs as the current user with limited rights, only while the
    user is logged on, on battery too (laptops), and never starts a second copy if
    the previous run is still going. Idempotent: rerun after moving the repository.

.PARAMETER RepoPath
    Repository root. Default: the parent of the folder holding this script.

.PARAMETER TaskName
    Default 'ClaudeSeat Backup to OneDrive'.

.PARAMETER Unregister
    Remove the task instead.

.EXAMPLE
    .\Register-ClaudeBackupTask.ps1
#>
[CmdletBinding()]
param(
    [Parameter()] [string]$RepoPath,
    [Parameter()] [string]$TaskName = 'ClaudeSeat Backup to OneDrive',
    [Parameter()] [switch]$Unregister
)
$ErrorActionPreference = 'Stop'

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
    return
}

if (-not $RepoPath) { $RepoPath = Split-Path -Parent $PSScriptRoot }
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).ProviderPath.TrimEnd('\')
$script = Join-Path $RepoPath 'scripts\Invoke-ClaudeSeatHourly.ps1'
if (-not (Test-Path -LiteralPath $script)) { throw "Not found: $script" }

$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$conhost    = Join-Path $env:SystemRoot 'System32\conhost.exe'
$arguments  = "--headless $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`""

$action = New-ScheduledTaskAction -Execute $conhost -Argument $arguments
$start  = (Get-Date).Date.AddHours((Get-Date).Hour).AddMinutes(45)
if ($start -lt (Get-Date)) { $start = $start.AddHours(1) }
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Hourly copy of the Claude Code home directory to OneDrive plus a commit into your copy of the shared-tooling repository. Source: $RepoPath" -Force | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "Registered '$TaskName' (state $($t.State)); first run $($start.ToString('yyyy-MM-dd HH:mm')), then hourly."
Write-Host "Runs: $conhost $arguments"
