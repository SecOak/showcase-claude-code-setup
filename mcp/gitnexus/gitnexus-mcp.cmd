@echo off
rem ---------------------------------------------------------------------------
rem gitnexus MCP launcher -- thin wrapper whose ONLY job is to stop discarding
rem the server's stderr.
rem
rem Why this exists: the gitnexus MCP server can fail its startup handshake
rem in a live session and leave ZERO evidence anywhere on the computer -- no
rem log, no exit code, nothing. The server emits structured JSON logs on stderr,
rem but Claude Code discards them. This wrapper tees that stderr to a file
rem instead, so a failure can be diagnosed.
rem
rem Source of truth: shared-tooling\mcp\gitnexus\gitnexus-mcp.cmd
rem Live target:     C:\Dev\claude-hooks\gitnexus-mcp.cmd  (deploy\Deploy-Hooks.ps1)
rem Registered in:   .claude.json top-level mcpServers (USER scope -> all repos)
rem
rem stdin/stdout MUST pass through untouched -- they are the JSON-RPC channel.
rem Only stderr (fd 2) is redirected. `call` is synchronous, so this process
rem lives exactly as long as the server does.
rem
rem ===========================================================================
rem ONE LOG FILE PER LAUNCH. Do not "tidy" this back to a fixed filename.
rem ===========================================================================
rem An earlier version appended to a single fixed path,
rem and that made gitnexus SINGLE-INSTANCE on the computer. Windows cmd opens a
rem redirect target with FILE_SHARE_READ only and holds it for the whole life of
rem the server, so the SECOND launch could not open the log -- cmd failed setting
rem up the redirect and never reached `call`. Measured with a server
rem already running: through this wrapper, "The process cannot access the file
rem because it is being used by another process", 0.0s, no server; the raw binary
rem on the same box answered initialize in 2.4s.
rem
rem What that cost:
rem   * gitnexus-health.py spawns its own probe instance through this wrapper, so
rem     the health check FAILED WHENEVER GITNEXUS WAS ACTUALLY WORKING, and its
rem     message blamed the binary.
rem   * the second of two concurrent Claude Code sessions silently got no
rem     gitnexus tools at all.
rem   * `exit /b %ERRORLEVEL%` returned 0 for a server that never started, so
rem     nothing downstream could tell.
rem
rem A unique name per launch removes the mutual exclusion and keeps the stderr
rem capture this wrapper exists for. gitnexus-health.py globs the newest one and
rem prunes the rest -- it must NEVER rename a log a live server still holds open.
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
if not exist "%TEMP%\mcp-logs\" md "%TEMP%\mcp-logs\" 2>nul
if not defined GITNEXUS_HOME set "GITNEXUS_HOME=%USERPROFILE%\.gitnexus-home"

rem ---------------------------------------------------------------------------
rem DO NOT replace this claim loop with "%RANDOM% is unique enough".
rem
rem %RANDOM% is seeded from the system clock, so two cmd processes started in the
rem same instant draw the SAME sequence. Measured: two concurrent
rem launches produced byte-identical names, even with two %RANDOM% concatenated.
rem Simultaneous launch is not the rare case here -- it is the normal one (two
rem Claude Code sessions starting, or gitnexus-health.py probing while a server
rem comes up). Randomness cannot provide uniqueness under an adversarial clock.
rem
rem `md` can. It is atomic and fails if the name is already taken, so exactly one
rem process wins a given name; the loser bumps a counter, which guarantees its
rem next attempt differs even in lockstep. The claim directory is held for the
rem life of the server so no other launch can reuse the log, and removed on exit.
rem Stale claims from a killed wrapper are pruned by hooks\gitnexus-health.py.
rem ---------------------------------------------------------------------------
set /a GNTRY=0
:gnpick
set /a GNTRY+=1
set "GNTAG=%USERNAME%-!RANDOM!-!GNTRY!"
md "%TEMP%\mcp-logs\.claim-!GNTAG!" 2>nul
if errorlevel 1 (
    if !GNTRY! lss 64 goto gnpick
    echo gitnexus-mcp.cmd: could not claim a log name after !GNTRY! tries 1>&2
    exit /b 78
)
set "GNLOG=%TEMP%\mcp-logs\gitnexus-mcp-!GNTAG!.log"

call "%USERPROFILE%\npm-global\gitnexus.cmd" mcp %* 2>>"!GNLOG!"
set "GNRC=!ERRORLEVEL!"
rd "%TEMP%\mcp-logs\.claim-!GNTAG!" 2>nul
exit /b !GNRC!
