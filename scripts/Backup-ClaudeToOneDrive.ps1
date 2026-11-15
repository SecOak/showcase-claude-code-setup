<#
.SYNOPSIS
    Copies the Claude Code home directory (~\.claude) and the root config file
    (~\.claude.json) into a dedicated folder inside the OneDrive sync root using
    robocopy (deletion-retaining). The OneDrive client then uploads the changes.

.DESCRIPTION
    Copies the Claude home
    tree into a script-owned subfolder of the local OneDrive folder via robocopy /E.
    It NEVER deletes from the destination (no /MIR, no /PURGE, no /MOV, no /MOVE).

    What is copied: CLAUDE.md, settings.json, memory, transcripts (projects), plans,
    history, plugin manifests, skills, output styles, feedback drafts, file history.
    What is skipped (regenerable or secret): plugin caches and marketplace clones,
    the agent-sdk virtual environment, shell snapshots, paste cache, session
    environments, any parked skills-disabled folder,
    node_modules and Python virtual environments, and .credentials.json (the sign-in
    token; sign in again on a rebuilt machine instead).

    Written to be Windows PowerShell 5.1 compatible so it runs from a scheduled task.

.PARAMETER Destination
    Dedicated backup folder inside the OneDrive sync root. Default:
    <OneDrive root>\ClaudeSeat\<COMPUTERNAME>. The script refuses any path that is
    not strictly below the OneDrive root.

.PARAMETER ClaudeHome
    The Claude Code config directory. Default: $env:CLAUDE_CONFIG_DIR, else ~\.claude.

.PARAMETER LogDirectory
    Directory for per-run logs. Default C:\ProgramData\DevBackup\logs.

.PARAMETER LogRetentionDays
    Logs written by THIS script older than this many days are pruned. Default 30.

.PARAMETER DryRun
    Preview only. Passes robocopy /L so nothing is written.

.EXAMPLE
    .\Backup-ClaudeToOneDrive.ps1 -DryRun

.NOTES
    Runtime: Windows PowerShell 5.1+ / PowerShell 7+
    Deps   : robocopy (in-box), OneDrive sync client signed in
    Creds  : none embedded.
    Exit codes: 0 = success (robocopy 0-7); 1 = robocopy failure (>=8);
                2 = precondition/validation error.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string]$Destination,

    [Parameter()]
    [string]$ClaudeHome,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$LogDirectory = 'C:\ProgramData\DevBackup\logs',

    [Parameter()]
    [ValidateRange(1, 3650)]
    [int]$LogRetentionDays = 30,

    [Parameter()]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Directory names excluded anywhere in the tree (robocopy /XD matches by name).
# 'cache' covers both ~\.claude\cache and ~\.claude\plugins\cache;
# 'marketplaces' covers ~\.claude\plugins\marketplaces (git clones, regenerable).
$excludeDirs  = @('cache', 'marketplaces', 'agent-sdk-venv', 'daemon', 'downloads',
                  'paste-cache', 'session-env', 'shell-snapshots', 'skills-disabled',
                  'node_modules', '.venv', 'venv', '__pycache__')
$excludeFiles = @('.credentials.json')

# --- Preconditions -----------------------------------------------------------
if (-not $ClaudeHome) {
    if ($env:CLAUDE_CONFIG_DIR) { $ClaudeHome = $env:CLAUDE_CONFIG_DIR }
    else { $ClaudeHome = Join-Path $env:USERPROFILE '.claude' }
}
if (-not (Test-Path -LiteralPath $ClaudeHome)) {
    Write-Error "Claude home not found: $ClaudeHome"
    exit 2
}
$ClaudeHome = (Resolve-Path -LiteralPath $ClaudeHome).ProviderPath.TrimEnd('\')
$rootConfig = Join-Path $env:USERPROFILE '.claude.json'

$oneDriveRoot = $env:OneDriveCommercial
if (-not $oneDriveRoot) { $oneDriveRoot = $env:OneDrive }
if (-not $oneDriveRoot -or -not (Test-Path -LiteralPath $oneDriveRoot)) {
    Write-Error "OneDrive sync root not found (OneDriveCommercial/OneDrive env vars). Refusing to run."
    exit 2
}
$oneDriveRoot = (Resolve-Path -LiteralPath $oneDriveRoot).ProviderPath.TrimEnd('\')

if (-not $Destination) { $Destination = Join-Path $oneDriveRoot ("ClaudeSeat\" + $env:COMPUTERNAME) }
$Destination = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
$homeDest    = Join-Path $Destination 'claude-home'
$rootDest    = Join-Path $Destination 'home-root'

if (-not $Destination.StartsWith($oneDriveRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Error "Destination '$Destination' is not inside the OneDrive root '$oneDriveRoot'. Refusing to write."
    exit 2
}
if ($homeDest.StartsWith($ClaudeHome + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    $ClaudeHome.StartsWith($homeDest + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    $homeDest -ieq $ClaudeHome) {
    Write-Error "Source and destination overlap. Refusing to run."
    exit 2
}

New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$stamp   = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$logFile = Join-Path $LogDirectory "claudeseat-onedrive-$stamp.log"

function Write-Log {
    param([string]$Message)
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding Ascii
    Write-Host $line
}

Write-Log "=== Claude home -> OneDrive backup started ==="
Write-Log "Source      : $ClaudeHome"
Write-Log "Destination : $homeDest"
Write-Log "DryRun      : $([bool]$DryRun)"

if (-not (Get-Process -Name OneDrive -ErrorAction SilentlyContinue)) {
    Write-Log "WARNING: OneDrive.exe is not running; files will upload once it starts."
}

if (-not $DryRun) {
    try {
        foreach ($d in @($homeDest, $rootDest)) {
            if (-not (Test-Path -LiteralPath $d)) {
                New-Item -ItemType Directory -Force -Path $d | Out-Null
                Write-Log "Created destination folder: $d"
            }
        }
    } catch {
        Write-Log "ERROR: destination not writable: $($_.Exception.Message)"
        Write-Log "=== Claude home -> OneDrive backup aborted ==="
        exit 2
    }
}

# --- Build robocopy arguments ------------------------------------------------
# /E deletion-retaining copy; /XJ skip junctions; /R:2 /W:2 retries; /FFT 2 second
# time tolerance; /NP no percent; /NDL no directory list; /LOG+ append; /TEE console.
$roboArgs = @($ClaudeHome, $homeDest, '/E', '/XJ', '/R:2', '/W:2', '/FFT', '/NP', '/NDL')
if ($DryRun) { $roboArgs += '/L' }
if (@($excludeDirs).Count  -gt 0) { $roboArgs += '/XD'; $roboArgs += $excludeDirs }
if (@($excludeFiles).Count -gt 0) { $roboArgs += '/XF'; $roboArgs += $excludeFiles }
$roboArgs += "/LOG+:$logFile"
$roboArgs += '/TEE'

$action = if ($DryRun) { "Preview copy (no changes)" } else { "Copy (deletion-retaining)" }
$code = 0
if ($PSCmdlet.ShouldProcess($homeDest, "$action of $ClaudeHome")) {
    Write-Log "robocopy $($roboArgs -join ' ')"
    & robocopy.exe @roboArgs | Out-Null
    $code = $LASTEXITCODE
} else {
    Write-Log "Skipped by -WhatIf; no robocopy executed."
    Write-Log "=== Claude home -> OneDrive backup finished (WhatIf) ==="
    return
}

# --- Root config file (~\.claude.json): MCP servers, per-project trust, history ---
# It holds no sign-in token (that lives in .credentials.json, which is excluded).
if (Test-Path -LiteralPath $rootConfig) {
    if ($DryRun) {
        Write-Log "Would copy $rootConfig -> $rootDest"
    } else {
        try {
            Copy-Item -LiteralPath $rootConfig -Destination $rootDest -Force
            Write-Log "Copied .claude.json -> $rootDest"
        } catch {
            Write-Log "WARNING: could not copy .claude.json: $($_.Exception.Message)"
        }
    }
}

# --- Prune this script's own old logs ---------------------------------------
try {
    $cutoff = (Get-Date).AddDays(-$LogRetentionDays)
    $old = @(Get-ChildItem -LiteralPath $LogDirectory -Filter 'claudeseat-onedrive-*.log' -File |
        Where-Object { $_.LastWriteTime -lt $cutoff })
    if ($old.Count -gt 0) {
        $old | Remove-Item -Force
        Write-Log "Pruned $($old.Count) log(s) older than $LogRetentionDays days."
    }
} catch {
    Write-Log "WARNING: log pruning failed: $($_.Exception.Message)"
}

Write-Log "robocopy exit code: $code"
if ($code -ge 8) {
    Write-Log "RESULT: FAILURE (exit >= 8)"
    Write-Log "=== Claude home -> OneDrive backup finished with errors ==="
    exit 1
} else {
    Write-Log "RESULT: SUCCESS (exit <= 7)"
    Write-Log "=== Claude home -> OneDrive backup finished ==="
    exit 0
}
