# Hooks

A hook is a small program Claude Code runs at a set moment, for example before every
shell command. The hooks here are Python files. `deploy\Deploy-Hooks.ps1 -Apply` copies
them to `C:\Dev\claude-hooks`, and `config\settings.json` points Claude Code at that
folder. Edit the copy in this repository, never the deployed copy, then deploy again.

| Hook | When it runs | What it does |
|------|--------------|--------------|
| `guard-destructive-azure-sql.py` | Before every Bash or PowerShell command | Sorts the command into three tiers: silent, ask, or block. |
| `context-reminders.py` | Before shell commands and file edits | Asks before `git push` and `gh pr create`; adds a short reminder when SQL is being written. |
| `statusline.py` | Continuously, in the status line | Shows user, model, folder and how full the conversation is. |
| `gitnexus-health.py` | At session start (not wired in by default) | Checks the optional gitnexus server is healthy. See [OPTIONAL-SERVERS.md](OPTIONAL-SERVERS.md). |
| `log-permission-prompt.ps1` | Not wired in by default | Appends each permission prompt to `%USERPROFILE%\.claude\permission-prompts.log`, useful for tuning your allow list. |

## The guard

Three tiers:

- **Silent**: reads and routine work inside your projects.
- **Ask**: consequential but recoverable, such as database writes, package installs,
  deletes outside your projects folder, cloud changes, rewriting Git history.
- **Block**: irreversible, such as `git push --force`, `git reset --hard`, database
  `DROP` or `TRUNCATE`, cloud resource deletion, deleting a path outside your projects.

Settings (environment variables, set in the `env` block of `settings.json`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `GUARD_HARD_BLOCK` | `1` in the shipped settings | `1` makes the block tier a hard deny. Anything else turns it into a question. |
| `GUARD_REPO_ROOT` | `%USERPROFILE%\repos` | Your projects folder. Deletes inside it are routine; outside it they are asked or blocked. |
| `GUARD_AUDIT_LOG` | `%USERPROFILE%\.claude\guard-audit.jsonl` | Where overrides are recorded. |

**Override:** when you really mean it, type the command yourself with the literal text
`#GUARD-OK` at the end. The guard lets it through and records it. Claude must never add
that text on its own; the starter `CLAUDE.md` does not allow it.

## Tests

Both test files are self-contained and change nothing on your computer:

```powershell
python hooks\test-guard-destructive.py
python hooks\test-context-reminders.py
```

Run them after any change to a hook, before you deploy.

## Wiring in an optional hook

Add an entry under `hooks` in `%USERPROFILE%\.claude\settings.json`. For example, the
permission prompt logger:

```json
"PermissionRequest": [
  { "hooks": [ { "type": "command", "command": "pwsh -NoProfile -File C:/Dev/claude-hooks/log-permission-prompt.ps1", "timeout": 10 } ] }
]
```

Then copy the change into `config\settings.json` (or let `Sync-ClaudeSeat.ps1` do it).
