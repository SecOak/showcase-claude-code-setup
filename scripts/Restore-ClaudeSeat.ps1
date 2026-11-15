<#
.SYNOPSIS
    Rebuilds your Claude Code setup on a fresh Windows computer from your copy of this
    repository, optionally pulling memory, transcripts and history back from the
    OneDrive backup made on your old computer.

.DESCRIPTION
    Run this from a clone of your own copy of this repository. Steps, each reported at the end
    as DONE, SKIPPED, or FAILED:

      1. Tools via winget (manifests\winget-packages.txt): Claude Code, Git, GitHub CLI,
         Node.js, Python, uv, PowerShell 7, gitleaks. Skipped for packages already present.
      2. npm global packages (manifests\npm-globals.txt): the language servers the
         code-intelligence plugins use (pyright, typescript-language-server, typescript).
      3. Config files into the Claude home: CLAUDE.md, settings.json, keybindings.json,
         output-styles\, skills\. Existing files are saved as *.pre-restore-<stamp> first.
      4. Memory: memory\<slug>\ -> <Claude home>\projects\<slug>\memory\ (never overwrites
         a newer file already there). The shared repository ships no memory; this step
         only does something in your own copy after Sync-ClaudeSeat.ps1 has captured it.
      5. ~\.gitconfig and the PowerShell 7 profile, only when they do not exist yet.
      6. Plugin marketplaces and plugins (config\plugins\*.json). The enabled/disabled
         state comes from settings.json.
      7. Model Context Protocol servers at user scope (config\mcp-servers.json).
      8. With -FromOneDrive: copies the OneDrive backup (transcripts, history, plans,
         feedback, file history, memory) into the Claude home without overwriting newer
         files, and restores ~\.claude.json only if none exists yet.
      9. With -RegisterBackupTask: registers the hourly backup task on this machine.

    Then sign in: run `claude` once. Nothing in this repository contains a credential.

    Windows PowerShell 5.1 compatible. Does not need elevation (winget installs that
    require it will raise a User Account Control prompt).

.PARAMETER RepoPath
    Repository root. Default: the parent of the folder holding this script.

.PARAMETER ClaudeHome
    Target Claude Code config directory. Default: $env:CLAUDE_CONFIG_DIR, else ~\.claude.

.PARAMETER SkipInstalls
    Skip steps 1 and 2 (winget and npm).

.PARAMETER SkipPlugins
    Skip steps 6 and 7 (plugins and MCP servers). Useful before the first sign-in.

.PARAMETER FromOneDrive
    Also restore from <OneDrive root>\ClaudeSeat\<SourceMachine>.

.PARAMETER SourceMachine
    Which machine's OneDrive backup to restore from. Default: the most recently
    modified folder under <OneDrive root>\ClaudeSeat.

.PARAMETER RegisterBackupTask
    Register the hourly scheduled task on this machine when done.

.PARAMETER DryRun
    Print what would happen; write nothing, install nothing.

.EXAMPLE
    # New computer, full restore including transcripts from the old computer's backup:
    .\Restore-ClaudeSeat.ps1 -FromOneDrive -SourceMachine <OLD_COMPUTER_NAME> -RegisterBackupTask

.EXAMPLE
    .\Restore-ClaudeSeat.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [Parameter()] [string]$RepoPath,
    [Parameter()] [string]$ClaudeHome,
    [Parameter()] [switch]$SkipInstalls,
    [Parameter()] [switch]$SkipPlugins,
    [Parameter()] [switch]$FromOneDrive,
    [Parameter()] [string]$SourceMachine,
    [Parameter()] [switch]$RegisterBackupTask,
    [Parameter()] [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = New-Object System.Collections.ArrayList

function Add-Result { param([string]$Step, [string]$Status, [string]$Detail)
    [void]$report.Add([pscustomobject]@{ Step = $Step; Status = $Status; Detail = $Detail })
    $color = switch ($Status) { 'DONE' { 'Green' } 'FAILED' { 'Red' } default { 'Yellow' } }
    Write-Host ("[{0,-7}] {1}: {2}" -f $Status, $Step, $Detail) -ForegroundColor $color
}
function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Test-Command { param([string]$Name) return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

if (-not $RepoPath) { $RepoPath = Split-Path -Parent $PSScriptRoot }
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).ProviderPath.TrimEnd('\')
if (-not $ClaudeHome) {
    if ($env:CLAUDE_CONFIG_DIR) { $ClaudeHome = $env:CLAUDE_CONFIG_DIR }
    else { $ClaudeHome = Join-Path $env:USERPROFILE '.claude' }
}
$cfg = Join-Path $RepoPath 'config'
$man = Join-Path $RepoPath 'manifests'
if (-not (Test-Path -LiteralPath $cfg)) { Write-Error "No config folder in $RepoPath. Is this the shared-tooling repository (or your copy of it)?"; exit 2 }

Write-Host "Restore-ClaudeSeat  repo=$RepoPath  home=$ClaudeHome  dryrun=$([bool]$DryRun)"
Write-Host ""

# --- 1. winget packages -----------------------------------------------------
if ($SkipInstalls) {
    Add-Result 'winget packages' 'SKIPPED' '-SkipInstalls'
} elseif (-not (Test-Command winget)) {
    Add-Result 'winget packages' 'FAILED' 'winget not found; install App Installer from the Microsoft Store, then rerun'
} else {
    $ids = Get-Content -LiteralPath (Join-Path $man 'winget-packages.txt') |
        ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ }
    $installed = @(); $skipped = @(); $failed = @()
    foreach ($id in $ids) {
        $present = (& winget list --id $id --exact --accept-source-agreements 2>$null | Select-String -SimpleMatch $id)
        if ($present) { $skipped += $id; continue }
        if ($DryRun) { Write-Host "  would install $id"; $installed += $id; continue }
        Write-Host "  installing $id ..."
        & winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
        if ($LASTEXITCODE -eq 0) { $installed += $id } else { $failed += "$id (exit $LASTEXITCODE)" }
    }
    Update-PathFromRegistry
    $detail = "installed: $($installed -join ', '); already present: $($skipped -join ', ')"
    if ($failed.Count -gt 0) { Add-Result 'winget packages' 'FAILED' ("failed: " + ($failed -join ', ') + "; " + $detail) }
    else { Add-Result 'winget packages' 'DONE' $detail }
}

# --- 2. npm globals ---------------------------------------------------------
if ($SkipInstalls) {
    Add-Result 'npm globals' 'SKIPPED' '-SkipInstalls'
} elseif (-not (Test-Command npm)) {
    Add-Result 'npm globals' 'FAILED' 'npm not on PATH (open a new shell after the Node.js install and rerun with -SkipPlugins)'
} else {
    $pkgs = Get-Content -LiteralPath (Join-Path $man 'npm-globals.txt') | ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ }
    if ($DryRun) { Add-Result 'npm globals' 'DONE' ("would install: " + ($pkgs -join ', ') + "; prefix $env:USERPROFILE\npm-global") }
    else {
        # Keep npm's global folder out of AppData. Packaged apps (the Claude desktop app among
        # them) get AppData writes redirected into a private package folder, so packages
        # installed from inside one are invisible to normal shells and scheduled tasks.
        $prefix = Join-Path $env:USERPROFILE 'npm-global'
        New-Item -ItemType Directory -Force -Path $prefix | Out-Null
        & npm config set prefix $prefix --location=user 2>&1 | Out-Null
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($userPath -notlike "*$prefix*") { [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $prefix), 'User') }
        Update-PathFromRegistry
        & npm install -g @pkgs 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Add-Result 'npm globals' 'DONE' ($pkgs -join ', ') }
        else { Add-Result 'npm globals' 'FAILED' "npm install -g exited $LASTEXITCODE" }
        Update-PathFromRegistry
    }
}

# --- 3. Config files --------------------------------------------------------
function Restore-File { param([string]$Rel, [string]$Dest)
    $src = Join-Path $cfg $Rel
    if (-not (Test-Path -LiteralPath $src)) { return "$Rel (not in repo)" }
    if ($DryRun) { return "$Rel -> $Dest" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dest) | Out-Null
    if ((Test-Path -LiteralPath $Dest) -and ((Get-FileHash $src).Hash -ne (Get-FileHash $Dest).Hash)) {
        Copy-Item -LiteralPath $Dest -Destination "$Dest.pre-restore-$stamp" -Force
    }
    Copy-Item -LiteralPath $src -Destination $Dest -Force
    return $Rel
}
function Restore-Dir { param([string]$Rel, [string]$Dest, [switch]$NoOverwriteNewer)
    $src = Join-Path $cfg $Rel
    if (-not (Test-Path -LiteralPath $src)) { return "$Rel (not in repo)" }
    if ($DryRun) { return "$Rel\ -> $Dest" }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $a = @($src, $Dest, '/E', '/XJ', '/R:1', '/W:1', '/FFT', '/NP', '/NDL', '/NJH', '/NJS', '/NFL')
    if ($NoOverwriteNewer) { $a += '/XO' }
    & robocopy.exe @a | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $Rel" }
    return "$Rel\"
}
try {
    $done = @()
    $done += Restore-File 'CLAUDE.md'        (Join-Path $ClaudeHome 'CLAUDE.md')
    $done += Restore-File 'settings.json'    (Join-Path $ClaudeHome 'settings.json')
    # Per-seat blocks ('permissions', 'autoMode') live in config\seat-local\<COMPUTERNAME>.settings.json
    # (see Sync-ClaudeSeat.ps1). Merge this machine's file, else _default for a new machine.
    $seatFile = Join-Path $cfg ("seat-local\" + $env:COMPUTERNAME + ".settings.json")
    if (-not (Test-Path -LiteralPath $seatFile)) { $seatFile = Join-Path $cfg 'seat-local\_default.settings.json' }
    if (Test-Path -LiteralPath $seatFile) {
        $dest = Join-Path $ClaudeHome 'settings.json'
        if ($DryRun) { $done += "seat-local: " + (Split-Path -Leaf $seatFile) + " -> $dest" }
        else {
            $merged = Get-Content -LiteralPath $dest -Raw -Encoding UTF8 | ConvertFrom-Json
            $seat = Get-Content -LiteralPath $seatFile -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $seat.PSObject.Properties) {
                if ($merged.PSObject.Properties.Name -contains $p.Name) { $merged.$($p.Name) = $p.Value }
                else { $merged | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value }
            }
            [System.IO.File]::WriteAllText($dest, ($merged | ConvertTo-Json -Depth 20) + "`n", (New-Object System.Text.UTF8Encoding($false)))
            $done += "seat-local: " + (Split-Path -Leaf $seatFile)
        }
    }
    $done += Restore-File 'keybindings.json' (Join-Path $ClaudeHome 'keybindings.json')
    $done += Restore-Dir  'output-styles'    (Join-Path $ClaudeHome 'output-styles')
    $done += Restore-Dir  'skills'           (Join-Path $ClaudeHome 'skills')
    Add-Result 'config files' 'DONE' ($done -join '; ')
} catch { Add-Result 'config files' 'FAILED' $_.Exception.Message }

# --- 4. Memory --------------------------------------------------------------
try {
    $memRoot = Join-Path $RepoPath 'memory'
    $slugs = @()
    foreach ($d in Get-ChildItem -LiteralPath $memRoot -Directory -ErrorAction SilentlyContinue) {
        $dest = Join-Path $ClaudeHome ("projects\" + $d.Name + "\memory")
        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            & robocopy.exe $d.FullName $dest /E /XO /XJ /R:1 /W:1 /FFT /NP /NDL /NJH /NJS /NFL | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for memory\$($d.Name)" }
        }
        $slugs += $d.Name
    }
    Add-Result 'memory' 'DONE' ("projects: " + ($slugs -join ', '))
} catch { Add-Result 'memory' 'FAILED' $_.Exception.Message }

# --- 5. gitconfig and PowerShell profile (only if absent) --------------------
try {
    $notes = @()
    $gc = Join-Path $env:USERPROFILE '.gitconfig'
    if (Test-Path -LiteralPath $gc) { $notes += '.gitconfig exists, left alone' }
    elseif (Test-Path -LiteralPath (Join-Path $cfg 'gitconfig')) {
        if (-not $DryRun) { Copy-Item -LiteralPath (Join-Path $cfg 'gitconfig') -Destination $gc }
        $notes += '.gitconfig restored'
    }
    $prof = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\Microsoft.PowerShell_profile.ps1'
    $profSrc = Join-Path $cfg 'powershell\Microsoft.PowerShell_profile.ps1'
    if (Test-Path -LiteralPath $prof) { $notes += 'PowerShell profile exists, left alone' }
    elseif (Test-Path -LiteralPath $profSrc) {
        if (-not $DryRun) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $prof) | Out-Null; Copy-Item -LiteralPath $profSrc -Destination $prof }
        $notes += "PowerShell profile restored to $prof"
    }
    Add-Result 'gitconfig + profile' 'DONE' ($notes -join '; ')
} catch { Add-Result 'gitconfig + profile' 'FAILED' $_.Exception.Message }

# --- 6. Plugins -------------------------------------------------------------
if ($SkipPlugins) {
    Add-Result 'plugins' 'SKIPPED' '-SkipPlugins'
} elseif (-not (Test-Command claude)) {
    Add-Result 'plugins' 'FAILED' 'claude not on PATH; open a new shell and rerun with -SkipInstalls'
} else {
    try {
        # Plugin manifests are per seat (see Sync-ClaudeSeat.ps1): this machine's pair, else _default.
        function Get-SeatManifest { param([string]$Name)
            $mine = Join-Path $cfg ("seat-local\" + $env:COMPUTERNAME + "." + $Name)
            if (Test-Path -LiteralPath $mine) { return $mine }
            return (Join-Path $cfg ("seat-local\_default." + $Name))
        }
        $mk = Get-Content -LiteralPath (Get-SeatManifest 'known_marketplaces.json') -Raw | ConvertFrom-Json
        $added = @()
        foreach ($name in ($mk | Get-Member -MemberType NoteProperty).Name) {
            $repo = $mk.$name.source.repo
            if (-not $repo) { continue }
            if (-not $DryRun) { & claude plugin marketplace add $repo 2>&1 | Out-Null }
            $added += $repo
        }
        $ip = Get-Content -LiteralPath (Get-SeatManifest 'installed_plugins.json') -Raw | ConvertFrom-Json
        $ok = @(); $bad = @()
        foreach ($id in ($ip.plugins | Get-Member -MemberType NoteProperty).Name) {
            if ($DryRun) { $ok += $id; continue }
            & claude plugin install $id --scope user 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $ok += $id } else { $bad += $id }
        }
        # Installing a plugin enables it, overriding the false written by step 3.
        # Re-apply the disabled state from the repository's settings.json.
        $repoSettings = Get-Content -LiteralPath (Join-Path $cfg 'settings.json') -Raw | ConvertFrom-Json
        foreach ($id in ($repoSettings.enabledPlugins | Get-Member -MemberType NoteProperty).Name) {
            if ($repoSettings.enabledPlugins.$id -eq $false -and -not $DryRun) {
                & claude plugin disable $id --scope user 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { $bad += "$id (disable)" }
            }
        }
        $detail = "marketplaces: $($added -join ', '); installed: $($ok -join ', ')"
        if ($bad.Count -gt 0) { Add-Result 'plugins' 'FAILED' ("failed: " + ($bad -join ', ') + " (sign in with `claude` first, then rerun with -SkipInstalls); " + $detail) }
        else { Add-Result 'plugins' 'DONE' $detail }
    } catch { Add-Result 'plugins' 'FAILED' $_.Exception.Message }
}

# --- 7. MCP servers (user scope) ----------------------------------------------
if ($SkipPlugins) {
    Add-Result 'mcp servers' 'SKIPPED' '-SkipPlugins'
} elseif (-not (Test-Command claude)) {
    Add-Result 'mcp servers' 'FAILED' 'claude not on PATH'
} else {
    try {
        $mcpFile = Join-Path $cfg 'mcp-servers.json'
        $ok = @(); $bad = @()
        if (Test-Path -LiteralPath $mcpFile) {
            $mcp = Get-Content -LiteralPath $mcpFile -Raw | ConvertFrom-Json
            foreach ($name in ($mcp | Get-Member -MemberType NoteProperty).Name) {
                $json = $mcp.$name | ConvertTo-Json -Depth 10 -Compress
                if ($DryRun) { $ok += $name; continue }
                & claude mcp get $name 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $ok += "$name (already present)"; continue }
                & claude mcp add-json $name $json --scope user 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { $ok += $name } else { $bad += $name }
            }
        }
        if ($bad.Count -gt 0) { Add-Result 'mcp servers' 'FAILED' ("failed: " + ($bad -join ', ') + "; ok: " + ($ok -join ', ')) }
        else { Add-Result 'mcp servers' 'DONE' ($ok -join ', ') }
    } catch { Add-Result 'mcp servers' 'FAILED' $_.Exception.Message }
}

# --- 8. OneDrive restore -------------------------------------------------------
if (-not $FromOneDrive) {
    Add-Result 'onedrive restore' 'SKIPPED' 'pass -FromOneDrive to pull transcripts, history and memory from the backup'
} else {
    try {
        $od = $env:OneDriveCommercial; if (-not $od) { $od = $env:OneDrive }
        if (-not $od -or -not (Test-Path -LiteralPath $od)) { throw 'OneDrive sync root not found; sign in to OneDrive first' }
        $seatRoot = Join-Path $od 'ClaudeSeat'
        if (-not $SourceMachine) {
            $newest = Get-ChildItem -LiteralPath $seatRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if (-not $newest) { throw "no machine folders under $seatRoot" }
            $SourceMachine = $newest.Name
        }
        $srcHome = Join-Path $seatRoot "$SourceMachine\claude-home"
        $srcRoot = Join-Path $seatRoot "$SourceMachine\home-root\.claude.json"
        if (-not (Test-Path -LiteralPath $srcHome)) { throw "backup not found: $srcHome (is the folder synced locally? Right-click it in OneDrive and choose Always keep on this device)" }
        $notes = @("from $SourceMachine")
        if (-not $DryRun) {
            & robocopy.exe $srcHome $ClaudeHome /E /XO /XJ /R:2 /W:2 /FFT /NP /NDL /NJH /NJS /NFL | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
            $notes += 'claude-home merged (newer local files kept)'
            $dstRoot = Join-Path $env:USERPROFILE '.claude.json'
            if (Test-Path -LiteralPath $srcRoot) {
                if (Test-Path -LiteralPath $dstRoot) { Copy-Item -LiteralPath $srcRoot -Destination "$dstRoot.from-backup" -Force; $notes += '.claude.json exists; backup copy saved as .claude.json.from-backup' }
                else { Copy-Item -LiteralPath $srcRoot -Destination $dstRoot; $notes += '.claude.json restored' }
            }
        } else { $notes += "would merge $srcHome -> $ClaudeHome" }
        Add-Result 'onedrive restore' 'DONE' ($notes -join '; ')
    } catch { Add-Result 'onedrive restore' 'FAILED' $_.Exception.Message }
}

# --- 9. Backup task ------------------------------------------------------------
if (-not $RegisterBackupTask) {
    Add-Result 'backup task' 'SKIPPED' 'pass -RegisterBackupTask, or run scripts\Register-ClaudeBackupTask.ps1 later'
} elseif ($DryRun) {
    Add-Result 'backup task' 'DONE' 'would register the hourly task'
} else {
    try {
        & (Join-Path $PSScriptRoot 'Register-ClaudeBackupTask.ps1') -RepoPath $RepoPath | Out-Null
        Add-Result 'backup task' 'DONE' 'hourly task registered'
    } catch { Add-Result 'backup task' 'FAILED' $_.Exception.Message }
}

# --- Report ----------------------------------------------------------------------
Write-Host ""
Write-Host "==== Restore report ($stamp) ===="
$report | Format-Table -AutoSize -Wrap | Out-String -Width 200 | Write-Host
Write-Host "Next: open a new terminal, run 'claude' and sign in, then 'claude plugin list' and 'claude mcp list'."
if (($report | Where-Object Status -eq 'FAILED').Count -gt 0) { exit 1 } else { exit 0 }
