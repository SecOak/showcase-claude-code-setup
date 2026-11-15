<#
.SYNOPSIS
    Mirrors the portable parts of this machine's Claude Code seat into this
    repository (config, memory, plugin and MCP manifests, tool manifests) and
    optionally commits and pushes.

.DESCRIPTION
    The repository is the "rebuild kit": Restore-ClaudeSeat.ps1 reads it on a new
    machine. This script keeps it current. It copies:

      config\CLAUDE.md                          <- ~\.claude\CLAUDE.md
      config\settings.json                      <- ~\.claude\settings.json
      config\keybindings.json                   <- ~\.claude\keybindings.json (if present)
      config\output-styles\                     <- ~\.claude\output-styles\
      config\skills\                            <- ~\.claude\skills\ (no .git, no node_modules)
      config\seat-local\<COMPUTERNAME>.installed_plugins.json  <- ~\.claude\plugins\installed_plugins.json
      config\seat-local\<COMPUTERNAME>.known_marketplaces.json <- ~\.claude\plugins\known_marketplaces.json
      config\mcp-servers.json                   <- the mcpServers block of ~\.claude.json
      config\gitconfig                          <- ~\.gitconfig
      config\powershell\Microsoft.PowerShell_profile.ps1 <- the PowerShell 7 profile
      memory\<project-slug>\                    <- ~\.claude\projects\<project-slug>\memory\
      manifests\npm-globals.txt                 <- npm ls -g --depth=0
      manifests\claude-version.txt              <- claude --version

    Inside the repository the config\ folders are true mirrors (a file deleted on the
    machine disappears from the working tree; git history keeps it). memory\ is a union
    across seats: files the repository has and this machine lacks are copied down into
    the machine's memory folder, newer files win in both directions, and nothing is
    deleted (remove a memory file in the repository by hand). That is the one write
    outside the repository this script makes.

    Before committing, every file in the working tree is scanned for secret-shaped
    strings. A hit aborts the commit with exit code 3. Known documentation placeholders
    listed in $knownPlaceholders are exempt.

    Windows PowerShell 5.1 compatible.

.PARAMETER RepoPath
    Repository root. Default: the parent of the folder holding this script.

.PARAMETER ClaudeHome
    The Claude Code config directory. Default: $env:CLAUDE_CONFIG_DIR, else ~\.claude.

.PARAMETER Commit
    Stage and commit when something changed.

.PARAMETER Push
    After a commit, run git push. Off by default (review what was captured before pushing).

.EXAMPLE
    .\Sync-ClaudeSeat.ps1                 # copy only, show git status
    .\Sync-ClaudeSeat.ps1 -Commit         # copy and commit
    .\Sync-ClaudeSeat.ps1 -Commit -Push   # copy, commit, push

.NOTES
    Exit codes: 0 = success; 2 = precondition error; 3 = secret scan hit; 4 = git failure.
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoPath,

    [Parameter()]
    [string]$ClaudeHome,

    [Parameter()]
    [switch]$Commit,

    [Parameter()]
    [switch]$Push
)

$ErrorActionPreference = 'Stop'

if (-not $RepoPath) { $RepoPath = Split-Path -Parent $PSScriptRoot }
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).ProviderPath.TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $RepoPath '.git'))) {
    Write-Error "Not a git repository: $RepoPath"
    exit 2
}
if (-not $ClaudeHome) {
    if ($env:CLAUDE_CONFIG_DIR) { $ClaudeHome = $env:CLAUDE_CONFIG_DIR }
    else { $ClaudeHome = Join-Path $env:USERPROFILE '.claude' }
}
if (-not (Test-Path -LiteralPath $ClaudeHome)) {
    Write-Error "Claude home not found: $ClaudeHome"
    exit 2
}
$ClaudeHome = (Resolve-Path -LiteralPath $ClaudeHome).ProviderPath.TrimEnd('\')

function Write-Log { param([string]$Message)
    Write-Host ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message)
}

# Mirror a directory into the repository. Guarded: destination must be inside the repository.
function Sync-Dir {
    param([string]$Source, [string]$Dest, [string[]]$ExcludeDirs = @(), [switch]$Union)
    if (-not $Dest.StartsWith($RepoPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to mirror outside the repository: $Dest"
    }
    if (-not (Test-Path -LiteralPath $Source)) {
        if (Test-Path -LiteralPath $Dest) { Remove-Item -LiteralPath $Dest -Recurse -Force }
        Write-Log "absent  $Source"
        return
    }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $common = @('/XJ', '/R:1', '/W:1', '/FFT', '/NP', '/NDL', '/NJH', '/NJS', '/NFL')
    if ($Union) {
        # Two computers may share one project slug (the same user folder name on both). A true mirror
        # would let each seat delete the other's files. Union instead: first bring down files
        # the repository has that this machine lacks or has older, then send up this machine's
        # newer or missing files. Nothing is deleted; remove a memory file in the repository by hand.
        & robocopy.exe $Dest $Source /E /XO @common | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) pulling $Dest" }
        $roboArgs = @($Source, $Dest, '/E', '/XO') + $common
    } else {
        $roboArgs = @($Source, $Dest, '/MIR') + $common
    }
    if ($ExcludeDirs.Count -gt 0) { $roboArgs += '/XD'; $roboArgs += $ExcludeDirs }
    & robocopy.exe @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $Source" }
    if ($Union) { Write-Log "union   $Source" } else { Write-Log "mirror  $Source" }
}

function Sync-File {
    param([string]$Source, [string]$Dest)
    if (-not $Dest.StartsWith($RepoPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside the repository: $Dest"
    }
    if (Test-Path -LiteralPath $Source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Dest -Force
        Write-Log "copy    $Source"
    } elseif (Test-Path -LiteralPath $Dest) {
        Remove-Item -LiteralPath $Dest -Force
        Write-Log "removed $Dest (source gone)"
    }
}

$cfg = Join-Path $RepoPath 'config'
New-Item -ItemType Directory -Force -Path $cfg, (Join-Path $RepoPath 'memory'), (Join-Path $RepoPath 'manifests') | Out-Null

# --- Config files -------------------------------------------------------------
Sync-File (Join-Path $ClaudeHome 'CLAUDE.md')        (Join-Path $cfg 'CLAUDE.md')
Sync-File (Join-Path $ClaudeHome 'settings.json')    (Join-Path $cfg 'settings.json')

# Per-seat settings: 'permissions' and 'autoMode' differ by machine on purpose (each seat
# has its own allow list and its own generated environment card). They are split out of the
# shared settings.json into config\seat-local\<COMPUTERNAME>.settings.json so that one seat's
# sync never overwrites the other seat's blocks. Restore merges the matching file back in.
$SeatLocalKeys = @('permissions', 'autoMode')
$sharedSettings = Join-Path $cfg 'settings.json'
if (Test-Path -LiteralPath $sharedSettings) {
    $settings = Get-Content -LiteralPath $sharedSettings -Raw -Encoding UTF8 | ConvertFrom-Json
    $seatLocal = New-Object PSObject
    foreach ($key in $SeatLocalKeys) {
        if ($settings.PSObject.Properties.Name -contains $key) {
            $seatLocal | Add-Member -NotePropertyName $key -NotePropertyValue $settings.$key
            $settings.PSObject.Properties.Remove($key)
        }
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($sharedSettings, ($settings | ConvertTo-Json -Depth 20) + "`n", $utf8NoBom)
    if (($seatLocal | Get-Member -MemberType NoteProperty | Measure-Object).Count -gt 0) {
        $seatDir = Join-Path $cfg 'seat-local'
        New-Item -ItemType Directory -Force -Path $seatDir | Out-Null
        $seatFile = Join-Path $seatDir ($env:COMPUTERNAME + '.settings.json')
        [System.IO.File]::WriteAllText($seatFile, ($seatLocal | ConvertTo-Json -Depth 20) + "`n", $utf8NoBom)
        Write-Log "seat-local settings -> config\seat-local\$env:COMPUTERNAME.settings.json"
    }
}
Sync-File (Join-Path $ClaudeHome 'keybindings.json') (Join-Path $cfg 'keybindings.json')
Sync-Dir  (Join-Path $ClaudeHome 'output-styles')    (Join-Path $cfg 'output-styles')
Sync-Dir  (Join-Path $ClaudeHome 'skills')           (Join-Path $cfg 'skills') @('.git', 'node_modules', '__pycache__')
# Plugin manifests record this machine's install paths and timestamps, so they are per seat
# (config\seat-local\<COMPUTERNAME>.installed_plugins.json and .known_marketplaces.json).
# Restore reads the matching pair, or the _default pair on a new machine.
Sync-File (Join-Path $ClaudeHome 'plugins\installed_plugins.json')  (Join-Path $cfg ("seat-local\" + $env:COMPUTERNAME + ".installed_plugins.json"))
Sync-File (Join-Path $ClaudeHome 'plugins\known_marketplaces.json') (Join-Path $cfg ("seat-local\" + $env:COMPUTERNAME + ".known_marketplaces.json"))
Sync-File (Join-Path $env:USERPROFILE '.gitconfig')  (Join-Path $cfg 'gitconfig')
$ps7Profile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Microsoft.PowerShell_profile.ps1'
Sync-File $ps7Profile (Join-Path $cfg 'powershell\Microsoft.PowerShell_profile.ps1')

# --- MCP servers (user scope) from ~\.claude.json -------------------------------
$rootConfig = Join-Path $env:USERPROFILE '.claude.json'
if (Test-Path -LiteralPath $rootConfig) {
    $root = Get-Content -LiteralPath $rootConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    $servers = $root.mcpServers
    if ($null -eq $servers) { $servers = New-Object PSObject }
    $json = $servers | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText((Join-Path $cfg 'mcp-servers.json'), $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Log "extract mcpServers -> config\mcp-servers.json"
}

# --- Memory: one folder per project slug ---------------------------------------
$memRoot = Join-Path $RepoPath 'memory'
$projRoot = Join-Path $ClaudeHome 'projects'
$liveSlugs = @()
if (Test-Path -LiteralPath $projRoot) {
    foreach ($proj in Get-ChildItem -LiteralPath $projRoot -Directory) {
        # Desktop app scratch sessions are throwaway; never mirror their memory.
        if ($proj.Name -match 'scratch-workspaces') { continue }
        $m = Join-Path $proj.FullName 'memory'
        # A junctioned memory folder aliases another slug (for example C--Users-<nameA> -> C--Users-<nameB>
        # on a machine with a different profile name); mirror only the real folder.
        if ((Test-Path -LiteralPath $m) -and ((Get-Item -LiteralPath $m -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        if (Test-Path -LiteralPath $m) {
            $liveSlugs += $proj.Name
            Sync-Dir $m (Join-Path $memRoot $proj.Name) -Union
        }
    }
}
# Drop a memory folder only when its project exists on this machine but no longer has a
# memory directory. A project that lives only on another machine is left alone; otherwise
# each machine's sync would delete the other machine's memory from the repository.
foreach ($d in Get-ChildItem -LiteralPath $memRoot -Directory -ErrorAction SilentlyContinue) {
    if ($liveSlugs -contains $d.Name) { continue }
    if (Test-Path -LiteralPath (Join-Path $projRoot $d.Name)) {
        Remove-Item -LiteralPath $d.FullName -Recurse -Force; Write-Log "removed memory\$($d.Name)"
    } else {
        Write-Log "kept    memory\$($d.Name) (project not on this machine)"
    }
}

# --- Manifests ----------------------------------------------------------------
$man = Join-Path $RepoPath 'manifests'
$utf8 = New-Object System.Text.UTF8Encoding($false)
try {
    $ErrorActionPreference = 'Continue'   # npm warnings on stderr must not abort (see the Git section)
    $npmErr = Join-Path $env:TEMP 'claudeseat-npm-stderr.txt'
    $npmJson = & npm ls -g --depth=0 --json 2>$npmErr | Out-String
    $npmExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($npmExit -ne 0 -or -not $npmJson.Trim()) {
        $detail = if (Test-Path -LiteralPath $npmErr) { (Get-Content -LiteralPath $npmErr -Raw).Trim() } else { '' }
        throw "npm ls exited $npmExit. $detail"
    }
    $npm = $npmJson | ConvertFrom-Json
    $lines = @()
    foreach ($p in ($npm.dependencies | Get-Member -MemberType NoteProperty | Sort-Object Name)) {
        $lines += ('{0}@{1}' -f $p.Name, $npm.dependencies.($p.Name).version)
    }
    # Never replace the manifest with an empty list because npm failed to run.
    if ($lines.Count -eq 0) { throw 'npm returned no global packages' }
    [System.IO.File]::WriteAllText((Join-Path $man 'npm-globals.txt'), (($lines -join "`n") + "`n"), $utf8)
    Write-Log "manifest npm-globals.txt ($($lines.Count) packages)"
} catch {
    $ErrorActionPreference = 'Stop'
    Write-Log "WARNING: npm manifest skipped: $($_.Exception.Message)"
}
try {
    $v = (& claude --version 2>$null | Out-String).Trim()
    if ($v) { [System.IO.File]::WriteAllText((Join-Path $man 'claude-version.txt'), $v + "`n", $utf8); Write-Log "manifest claude-version.txt ($v)" }
} catch {
    Write-Log "WARNING: claude version skipped: $($_.Exception.Message)"
}

# --- Secret scan ---------------------------------------------------------------
$patterns = @(
    'sk-ant-[A-Za-z0-9_\-]{20,}',          # Anthropic API key
    'gh[pousr]_[A-Za-z0-9]{30,}',           # GitHub tokens
    'AKIA[0-9A-Z]{16}',                     # AWS access key id
    'xox[baprs]-[A-Za-z0-9\-]{10,}',        # Slack tokens
    '-----BEGIN [A-Z ]*PRIVATE KEY-----',   # private keys
    '(?i)(password|passwd|client_secret|connectionstring)\s*[=:]\s*["'']?[^\s"'']{8,}',
    'eyJ[A-Za-z0-9_\-]{20,}\.eyJ[A-Za-z0-9_\-]{20,}\.'   # JSON Web Token
)
# Documentation examples that match a pattern but are not secrets (the Anthropic pdf
# skill's qpdf samples). Each exact, case-sensitive string is removed before scanning,
# so the same pattern still catches any other value.
$knownPlaceholders = @(
    '--password=secret123',
    '--password=mypassword'
)
$hits = @()
$files = Get-ChildItem -LiteralPath $RepoPath -Recurse -File | Where-Object { $_.FullName -notmatch '\\\.git\\' }
foreach ($f in $files) {
    $text = [System.IO.File]::ReadAllText($f.FullName)
    foreach ($k in $knownPlaceholders) { $text = $text.Replace($k, '') }
    foreach ($p in $patterns) {
        if ($text -match $p) { $hits += ('{0}  ({1})' -f $f.FullName.Substring($RepoPath.Length + 1), $p); break }
    }
}
if ($hits.Count -gt 0) {
    Write-Host ""
    Write-Host "SECRET SCAN HIT - not committing:" -ForegroundColor Red
    $hits | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    exit 3
}
Write-Log "secret scan clean ($($files.Count) files)"

# --- Git -----------------------------------------------------------------------
# Windows PowerShell 5.1 turns any native stderr line (such as git's CRLF warning) into a
# terminating error under 'Stop' when the caller redirects streams, as the hourly task does.
# Exit codes are checked explicitly below instead.
$ErrorActionPreference = 'Continue'
Push-Location $RepoPath
try {
    & git add -A
    & git diff --cached --quiet
    $changed = ($LASTEXITCODE -ne 0)
    if (-not $changed) {
        Write-Log "git: nothing to commit"
    } elseif ($Commit) {
        $stat = (& git diff --cached --numstat | Measure-Object).Count
        $msg = 'sync: {0} {1} ({2} files)' -f $env:COMPUTERNAME, (Get-Date -Format 'yyyy-MM-dd HH:mm'), $stat
        & git commit -q -m $msg
        if ($LASTEXITCODE -ne 0) { Write-Log "git commit failed"; exit 4 }
        Write-Log "git: committed '$msg'"
        if ($Push) {
            & git push -q
            if ($LASTEXITCODE -ne 0) { Write-Log "git push failed"; exit 4 }
            Write-Log "git: pushed"
        }
    } else {
        Write-Log "git: changes staged, not committed (pass -Commit)"
        & git status --short
    }
} finally {
    Pop-Location
}
exit 0
