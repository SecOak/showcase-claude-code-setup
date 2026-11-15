@echo off
rem ---------------------------------------------------------------------------
rem qmd MCP launcher -- keyword search (BM25) over your markdown notes for Claude Code.
rem
rem Modelled on gitnexus-mcp.cmd; read that file's header for WHY the stderr tee
rem and the atomic `md` log-claim exist.
rem
rem Source of truth: shared-tooling\mcp\qmd\qmd-mcp.cmd
rem Live target:     C:\Dev\claude-hooks\qmd-mcp.cmd  (deploy\Deploy-Hooks.ps1)
rem Register once (USER scope, all projects):
rem   claude mcp add qmd --scope user -- C:\Dev\claude-hooks\qmd-mcp.cmd
rem
rem Binary: %USERPROFILE%\npm-global\qmd.cmd (npm install -g @tobilu/qmd). The index
rem lives under %USERPROFILE%\.claude\%USERNAME%\ unless XDG_CACHE_HOME and
rem XDG_CONFIG_HOME are already set.
rem
rem KEYWORD MODE IS THE SAFE DEFAULT. On a computer without a graphics card, CPU
rem embedding is very slow (tens of seconds per chunk). `qmd mcp` exposes query/get/
rem multi_get/status; its `query` tool falls back to BM25 when no vectors exist.
rem
rem stdin/stdout MUST pass through untouched -- they are the JSON-RPC channel.
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
if not exist "%TEMP%\mcp-logs\" md "%TEMP%\mcp-logs\" 2>nul
if not defined XDG_CACHE_HOME  set "XDG_CACHE_HOME=%USERPROFILE%\.claude\%USERNAME%\qmd-cache"
if not defined XDG_CONFIG_HOME set "XDG_CONFIG_HOME=%USERPROFILE%\.claude\%USERNAME%\qmd-config"
set "QMD_FORCE_CPU=1"

rem Atomic per-launch log claim -- see gitnexus-mcp.cmd for why %RANDOM% alone is not enough.
set /a QMTRY=0
:qmpick
set /a QMTRY+=1
set "QMTAG=%USERNAME%-!RANDOM!-!QMTRY!"
md "%TEMP%\mcp-logs\.claim-qmd-!QMTAG!" 2>nul
if errorlevel 1 (
    if !QMTRY! lss 64 goto qmpick
    echo qmd-mcp.cmd: could not claim a log name after !QMTRY! tries 1>&2
    exit /b 78
)
set "QMLOG=%TEMP%\mcp-logs\qmd-mcp-!QMTAG!.log"

call "%USERPROFILE%\npm-global\qmd.cmd" mcp %* 2>>"!QMLOG!"
set "QMRC=!ERRORLEVEL!"
rd "%TEMP%\mcp-logs\.claim-qmd-!QMTAG!" 2>nul
exit /b !QMRC!
