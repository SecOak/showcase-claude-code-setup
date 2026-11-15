<#
.SYNOPSIS
    First script to run on a brand-new Windows computer. Installs Git and the GitHub
    command-line tool, clones your copy of this repository, deploys the hooks, and
    restores your Claude Code configuration.

.DESCRIPTION
    Steps, in order:
      1. Installs Git, the GitHub command-line tool and PowerShell 7 with winget, if missing.
      2. Clones -RepoUrl into -Destination, unless that folder already exists.
      3. Runs scripts\Restore-ClaudeSeat.ps1 from the clone (tools, npm packages,
         config files, plugins, Model Context Protocol servers). Extra switches are
         passed through: -FromOneDrive, -SourceMachine, -RegisterBackupTask, -SkipPlugins.
      4. Runs deploy\Deploy-Hooks.ps1 -Apply so the hooks exist in C:\Dev\claude-hooks.

    Safe to run again: every step skips work that is already done.
    Windows PowerShell 5.1 compatible. No elevation needed; winget may raise a
    User Account Control prompt for some installers.

.PARAMETER RepoUrl
    The clone address of YOUR copy, for example https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git

.PARAMETER Destination
    Where to clone. Default: $env:USERPROFILE\repos\shared-tooling.

.EXAMPLE
    .\Bootstrap-NewComputer.ps1 -RepoUrl https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git

.EXAMPLE
    .\Bootstrap-NewComputer.ps1 -RepoUrl https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git -FromOneDrive -RegisterBackupTask
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$RepoUrl,
    [Parameter()] [string]$Destination = (Join-Path $env:USERPROFILE 'repos\shared-tooling'),
    [Parameter()] [switch]$FromOneDrive,
    [Parameter()] [string]$SourceMachine,
    [Parameter()] [switch]$RegisterBackupTask,
    [Parameter()] [switch]$SkipPlugins
)
$ErrorActionPreference = 'Stop'

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

# --- 1. Minimum tools ---------------------------------------------------------
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'winget is missing. Install "App Installer" from the Microsoft Store, then run this again.'
}
foreach ($pair in @(@('git', 'Git.Git'), @('gh', 'GitHub.cli'), @('pwsh', 'Microsoft.PowerShell'))) {
    if (Get-Command $pair[0] -ErrorAction SilentlyContinue) {
        Write-Host "present  $($pair[1])"
        continue
    }
    Write-Host "install  $($pair[1])"
    & winget install --id $pair[1] --exact --silent --accept-package-agreements --accept-source-agreements
    Update-SessionPath
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git is still not on PATH. Open a new PowerShell window and run this again.' }

# --- 2. Clone your copy ---------------------------------------------------------
if (Test-Path -LiteralPath (Join-Path $Destination '.git')) {
    Write-Host "present  $Destination (not cloned again; run 'git pull' there to update)"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Write-Host "clone    $RepoUrl -> $Destination"
    Write-Host '         (a private repository opens a browser sign-in the first time)'
    & git clone $RepoUrl $Destination
    if ($LASTEXITCODE -ne 0) { throw "git clone failed. For a private repository run 'gh auth login' first, then run this again." }
}

# --- 3. Restore -----------------------------------------------------------------
$restoreArgs = @{ RepoPath = $Destination }
if ($FromOneDrive)       { $restoreArgs.FromOneDrive = $true }
if ($SourceMachine)      { $restoreArgs.SourceMachine = $SourceMachine }
if ($RegisterBackupTask) { $restoreArgs.RegisterBackupTask = $true }
if ($SkipPlugins)        { $restoreArgs.SkipPlugins = $true }
& (Join-Path $Destination 'scripts\Restore-ClaudeSeat.ps1') @restoreArgs

# --- 4. Hooks -------------------------------------------------------------------
& (Join-Path $Destination 'deploy\Deploy-Hooks.ps1') -Apply

Write-Host ''
Write-Host 'Done. Next: open a new PowerShell window, run "claude", and sign in.' -ForegroundColor Green
Write-Host 'If the plugins step failed because you were not signed in yet, run:'
Write-Host "  & '$Destination\scripts\Restore-ClaudeSeat.ps1' -SkipInstalls"
