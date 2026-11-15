# My Claude Code rules

This file is loaded into every Claude Code session on this computer. It lives at
`%USERPROFILE%\.claude\CLAUDE.md`. Edit it freely; `Sync-ClaudeSeat.ps1` copies your
version back into your repository.

## How to work with me
1. Any command I must run myself goes in its own code block, ready to copy and paste,
   with the shell named above it (PowerShell 7, Git Bash, or Command Prompt).
2. Write in full words. No abbreviations, no unexplained jargon.
3. Answer first, then explain.
4. Read-only commands (listing, searching, reading) can run freely.
5. Ask before anything that changes shared or online state: `git push`, opening a pull
   request, deleting files outside the current project, or changing cloud resources.
6. Commit freely inside a project repository, with plain commit messages.
7. Never print, log or commit secrets, passwords, tokens, keys or connection strings.
   If one appears, stop and tell me.
8. When the guard hook blocks a command, stop and explain. Never add `#GUARD-OK`
   yourself; only I type that.

## How to approach work
1. Think before coding. State your assumptions and the simplest approach first.
2. Make small, surgical changes. Do not rewrite what you were not asked to change.
3. Verify every step with a real check (run the test, parse the file, read it back).
4. Before a big move or bulk rewrite of files, commit or copy what is there first.
5. If something fails twice the same way, stop and explain instead of trying again.

## Subagents and models (optional; delete this section if you do not use subagents)
- Hand large reading, searching and mechanical editing to subagents so the main
  conversation stays small.
- Pick the smallest model that fits the job:
  - haiku: trivial lookups, file listings, single facts.
  - sonnet: searches, writing code or documents from a clear specification, tests.
  - opus: design, security questions, code review, anything risky.
- Give each subagent one bounded task. Run independent tasks in parallel.
