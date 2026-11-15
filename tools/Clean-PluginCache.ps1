<#
.SYNOPSIS
    Removes the temp_git_* and temp_subdir_* folders Claude Code leaves behind in its
    plugin cache.

.DESCRIPTION
    Claude Code can leak dozens of these temporary folders into the plugin cache every
    day and never reclaims them. The named plugin folders are left untouched.

    Deletes only folders OLDER THAN ONE DAY: a running session holds only the folders it
    created at its own start, so age is the liveness test. (A "skip if claude.exe is
    running" check does not work, because the Claude desktop app is also Claude.exe.)

    The weekly scheduled task registered by tools\Register-CleanPluginCache.ps1 runs the
    DEPLOYED copy in C:\Dev\claude-hooks. Edit the copy in this repository, then run
    deploy\Deploy-Hooks.ps1 -Apply.

.PARAMETER ClaudeHome
    The Claude Code config directory. Default: $env:CLAUDE_CONFIG_DIR, else ~\.claude.
#>
[CmdletBinding()]
param([Parameter()] [string]$ClaudeHome)

if (-not $ClaudeHome) {
    if ($env:CLAUDE_CONFIG_DIR) { $ClaudeHome = $env:CLAUDE_CONFIG_DIR }
    else { $ClaudeHome = Join-Path $env:USERPROFILE '.claude' }
}
$cache  = Join-Path $ClaudeHome 'plugins\cache'
$log    = Join-Path $env:TEMP 'plugin-cache-clean.log'
$cutoff = (Get-Date).AddDays(-1)
if (-not (Test-Path -LiteralPath $cache)) { return }

$dirs = @(Get-ChildItem -LiteralPath $cache -Directory |
    Where-Object { $_.Name -match '^temp_(git|subdir)_' -and $_.LastWriteTime -lt $cutoff })
foreach ($d in $dirs) { Remove-Item -LiteralPath $d.FullName -Recurse -Force }
$left = @(Get-ChildItem -LiteralPath $cache -Directory).Count
"$(Get-Date -Format s) CLEAN deleted $($dirs.Count) folder(s) older than 1 day; $left folder(s) remain" | Add-Content $log
