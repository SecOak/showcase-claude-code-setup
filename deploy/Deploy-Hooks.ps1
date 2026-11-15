<#
.SYNOPSIS
    Deploys hooks and MCP launchers from this repository to their live paths on this
    machine, reporting drift first. The repository is the source; the live copies are
    what Claude Code runs.

.DESCRIPTION
    Deploy map (source, relative to this repository -> live target):

      hooks\guard-destructive-azure-sql.py  -> C:\Dev\claude-hooks\guard-destructive-azure-sql.py
      hooks\context-reminders.py            -> C:\Dev\claude-hooks\context-reminders.py
      hooks\gitnexus-health.py              -> C:\Dev\claude-hooks\gitnexus-health.py
      hooks\log-permission-prompt.ps1       -> C:\Dev\claude-hooks\log-permission-prompt.ps1
      hooks\statusline.py                   -> C:\Dev\claude-hooks\statusline.py
      mcp\gitnexus\gitnexus-mcp.cmd         -> C:\Dev\claude-hooks\gitnexus-mcp.cmd
      mcp\qmd\qmd-mcp.cmd                   -> C:\Dev\claude-hooks\qmd-mcp.cmd
      tools\Clean-PluginCache.ps1           -> C:\Dev\claude-hooks\Clean-PluginCache.ps1

    The live folder is a fixed path, not under the user profile, so one hooks block in the
    shared settings.json works on every computer regardless of the user folder name.
    Pass -LiveRoot to use another folder, and change the paths in settings.json to match.

    A bare run compares hashes and prints one line per target: in sync, missing, behind
    (repository is newer), or HAND-EDITED (live differs from both the repository copy and
    the last deployed hash). -Apply copies repository sources over targets that are missing
    or behind; a HAND-EDITED target is never overwritten without -Force. The hash of every
    deployed file is recorded in C:\Dev\claude-hooks\.deployed.json.

    Windows PowerShell 5.1 compatible. No elevation needed.

.PARAMETER Apply
    Copy sources to targets that are missing or behind.

.PARAMETER Force
    With -Apply, also overwrite HAND-EDITED targets.

.PARAMETER LiveRoot
    The live folder. Default C:\Dev\claude-hooks.

.EXAMPLE
    .\Deploy-Hooks.ps1            # drift report
    .\Deploy-Hooks.ps1 -Apply
#>
[CmdletBinding()]
param(
    [Parameter()] [switch]$Apply,
    [Parameter()] [switch]$Force,
    [Parameter()] [string]$LiveRoot = 'C:\Dev\claude-hooks'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$liveRoot = $LiveRoot
$manifestPath = Join-Path $liveRoot '.deployed.json'

$map = [ordered]@{
    'hooks\guard-destructive-azure-sql.py' = 'guard-destructive-azure-sql.py'
    'hooks\context-reminders.py'           = 'context-reminders.py'
    'hooks\gitnexus-health.py'             = 'gitnexus-health.py'
    'hooks\log-permission-prompt.ps1'      = 'log-permission-prompt.ps1'
    'hooks\statusline.py'                  = 'statusline.py'
    'mcp\gitnexus\gitnexus-mcp.cmd'        = 'gitnexus-mcp.cmd'
    'mcp\qmd\qmd-mcp.cmd'                  = 'qmd-mcp.cmd'
    'tools\Clean-PluginCache.ps1'          = 'Clean-PluginCache.ps1'
}

New-Item -ItemType Directory -Force -Path $liveRoot | Out-Null
$deployed = @{}
if (Test-Path -LiteralPath $manifestPath) {
    $j = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $j.PSObject.Properties) { $deployed[$p.Name] = $p.Value }
}

function Get-Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }

$rows = @(); $applied = 0; $blocked = 0; $missingSources = 0
foreach ($src in $map.Keys) {
    $srcPath = Join-Path $repoRoot $src
    $dstPath = Join-Path $liveRoot $map[$src]
    if (-not (Test-Path -LiteralPath $srcPath)) { $rows += "{0,-12} {1}  (source not in repository yet)" -f 'NO SOURCE', $src; $missingSources++; continue }
    $srcHash = Get-Hash $srcPath
    $state = 'missing'
    if (Test-Path -LiteralPath $dstPath) {
        $dstHash = Get-Hash $dstPath
        if ($dstHash -eq $srcHash) { $state = 'in sync' }
        elseif ($deployed.ContainsKey($map[$src]) -and $deployed[$map[$src]] -eq $dstHash) { $state = 'behind' }
        else { $state = 'HAND-EDITED' }
    }
    $action = ''
    if ($Apply -and ($state -eq 'missing' -or $state -eq 'behind' -or ($state -eq 'HAND-EDITED' -and $Force))) {
        Copy-Item -LiteralPath $srcPath -Destination $dstPath -Force
        $deployed[$map[$src]] = $srcHash
        $action = ' -> deployed'; $applied++
    } elseif ($Apply -and $state -eq 'HAND-EDITED') {
        $action = ' -> left alone (use -Force to overwrite)'; $blocked++
    }
    $rows += "{0,-12} {1}{2}" -f $state, $src, $action
}
$rows | ForEach-Object { Write-Host $_ }

if ($Apply) {
    $ordered = [ordered]@{}
    foreach ($k in ($deployed.Keys | Sort-Object)) { $ordered[$k] = $deployed[$k] }
    [System.IO.File]::WriteAllText($manifestPath, (($ordered | ConvertTo-Json) + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ("deployed {0}, left alone {1}, no source {2}" -f $applied, $blocked, $missingSources)
} else {
    Write-Host 'Drift report only. Add -Apply to deploy.'
}
if ($blocked -gt 0) { exit 1 }
exit 0
