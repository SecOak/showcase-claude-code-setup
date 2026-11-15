# Claude Code setup: hooks, guardrails, and a reproducible seat

> **Showcase copy.** This is a sanitized snapshot of the setup I actually run, published for
> portfolio purposes. It is not actively maintained here. Issues and pull requests are welcome
> but may not get a reply. Contact: zachanger@outlook.com · [zachanger.com](https://zachanger.com)

## What this demonstrates

I use AI agents as a working tool in IT operations, not as a chatbot. That only works if the
agent is boxed in properly, so this repository is mostly about the box:

- **A guard hook that sits in front of every command.** It blocks or asks before force pushes,
  recursive deletes outside the project, database drops, cloud deletions, and secret writes.
  An override is an explicit marker that is recorded in an audit log. The guard is a seatbelt,
  not a sandbox. It ships with a test suite (`hooks/test-guard-destructive.py`) covering
  quoting edge cases and commit messages that merely mention dangerous commands.
- **Context reminders at the moment they matter** (before a `git push`, when the conversation
  is getting long), plus a status line showing how full the context window is.
- **A permissions model, not a blanket allow.** `settings.json` allows the read-only and
  project-scoped tools and denies the rest by default; `.env`, `secrets/` and raw network
  tools are denied outright.
- **Working rules the agent is loaded with** (`config/CLAUDE.md`): answer first, small surgical
  changes, verify with a real check, stop after two identical failures, and never add the
  guard token itself. Subagent and model-routing rules keep the main context small and send
  risky work to the strongest model.
- **Secret hygiene by default.** A gitleaks pre-commit hook and a sync script that scans before
  it commits, so a token never lands in git by accident.
- **A reproducible seat.** One bootstrap script rebuilds the whole setup on a new Windows
  machine from package manifests, and an hourly task backs the live configuration up.

## How the pieces fit

This repository is one of several that make up my working setup. The others stay private
because their content is the sensitive part, not just their config, so here is how they fit
together instead.

**Seat.** Everything Claude Code needs on a given machine: `CLAUDE.md`, settings, hooks, skills,
agent definitions, and per-machine overrides. Versioned, so a new laptop is a clone and one
script. This repository is the sanitized shape of that seat.

**Memory.** A separate private repository of short markdown notes, one per fact or decision
("times in Eastern", "no abbreviations", "status report format", "phase 7 state of project X").
Each session starts by reading the ones that matter, so the agent picks up where the last one
stopped without me re-explaining anything. Notes are small, named by subject, and get deleted
when they stop being true.

**Pickup.** A start-of-session skill that pulls the seat, fetches every tracked repository,
reports which ones are dirty or behind, and surfaces the most recent handoff notes and open
items. Read-only by design. It exists so the first five minutes of a session are a report,
not an archaeology dig.

**Agent classes.** Work is handed to subagents by role, not by task name. Five classes, each
with a lane it owns, things folded in, and a short list of things it never does:

| Class | Owns | Model | Never does |
|---|---|---|---|
| Code manager | implementation in an assigned scope, tests, schema changes, release prep | mid-tier | tenant changes, deploys, destructive actions |
| Product manager | backlog, work orders, decision log, user-facing docs and copy | mid-tier | code, anything in the tenant |
| Testing manager | verification runs, smoke tests, fixtures, evidence capture | mid-tier | fixing what it finds |
| Security manager | permission analysis, test plans, guard and policy changes, health-check readouts | strongest | the security *decision* (severity, exceptions) |
| Review and rescue | primary review of code and designs; one rescue pass when another class is stuck | strongest | reading the repo beyond what it was handed, taking over the task |

Rules that apply to all five: they receive a bounded work order and return exactly seven
fields (status, what changed, tests run, failures, what is left, blocker and attempts, proposed
next task and owner). Status is `done`, `partial` or `blocked`, nothing else. They run once per
item; a second pass on the same item needs a human. They never claim a test passed without
showing the output, never widen their own scope, and never touch Entra ID, Intune, Exchange,
Conditional Access, or anything the guard hook would block. The verdict always stays with me.

**Guard and permissions.** The hooks and settings in this repository are the floor under all
of the above. An agent class can be told "never force-push"; the guard backs that
instruction with a hard block instead of trusting it.

The agent definitions and the pickup skill are not included here because they were written for
a team environment and are not mine alone to publish. The design above is.

Everything below is the original operator-facing guide.

---

A starter kit for setting up Claude Code on a Windows computer, and for moving your
setup to the next computer without starting over.

It gives you:

- **Setup scripts** that install the tools, restore your Claude Code configuration, and
  deploy the hooks on a new computer.
- **Backup scripts** that capture your configuration from your current computer into
  your own copy of this repository, and optionally back up your whole Claude Code folder
  to OneDrive every hour.
- **Hooks** (small programs Claude Code runs before a tool call):
  - a guard that asks or blocks before destructive commands (force pushes, recursive
    deletes outside your projects, database drops, cloud deletions);
  - context reminders that ask before `git push` and add short reminders at the moment
    they matter;
  - a status line that shows how full the conversation is.
- **Settings patterns**: a `settings.json` with the hooks wired in, a sensible permission
  allow and deny list, and a starter set of plugins.
- **A starter `CLAUDE.md`** with general working rules you can edit.
- **One skill and one output style**: PowerShell coding standards, and a plain,
  answer-first reply style.

Nothing in this repository contains a password, token or sign-in. You sign in to Claude
Code and GitHub yourself.

## Start here

1. Read [docs/MOVE-TO-YOUR-OWN-GITHUB.md](docs/MOVE-TO-YOUR-OWN-GITHUB.md) and make your own
   private copy. Your copy is where your own settings get saved.
2. On a new computer, follow [docs/NEW-COMPUTER.md](docs/NEW-COMPUTER.md) from top to bottom.
3. To pick up improvements made to this shared repository later, follow
   [docs/KEEPING-IT-UPDATED.md](docs/KEEPING-IT-UPDATED.md).
4. To learn what each hook does and how to adjust it, read [docs/HOOKS.md](docs/HOOKS.md).

## Layout

| Path | What it is |
|------|------------|
| `scripts/Bootstrap-NewComputer.ps1` | First script on a new computer: installs Git, clones your copy, runs the restore, deploys the hooks. |
| `scripts/Restore-ClaudeSeat.ps1` | Installs the tools in `manifests/`, copies `config/` into `%USERPROFILE%\.claude`, installs plugins and servers. |
| `scripts/Sync-ClaudeSeat.ps1` | Run on your current computer: copies your live configuration back into your copy of this repository and can commit it. |
| `scripts/Backup-ClaudeToOneDrive.ps1` | Copies your whole Claude Code folder (including conversation history) into OneDrive. Never deletes. |
| `scripts/Register-ClaudeBackupTask.ps1` | Registers an hourly scheduled task that runs the backup and the sync. |
| `scripts/Invoke-ClaudeSeatHourly.ps1` | What that hourly task runs. |
| `deploy/Deploy-Hooks.ps1` | Copies the hooks and launchers from this repository to `C:\Dev\claude-hooks`, where `settings.json` expects them. |
| `hooks/` | The hook programs (Python) and their tests. |
| `mcp/` | Optional launchers for two Model Context Protocol servers (gitnexus and qmd). |
| `tools/` | Plugin cache cleaner and its weekly scheduled task, and a Markdown to Word converter. |
| `config/` | What gets copied into `%USERPROFILE%\.claude`: `CLAUDE.md`, `settings.json`, skills, output styles, plugin lists. |
| `config/seat-local/` | Settings that differ per computer (permissions and plugin lists). `_default.*` is used when no file matches the computer name. |
| `manifests/` | The winget and npm package lists the restore installs. |
| `.githooks/pre-commit` | Runs gitleaks before every commit so a secret never gets committed. |
| `docs/` | The step-by-step guides. |

## New computer, short version

The full checklist, with explanations, is in [docs/NEW-COMPUTER.md](docs/NEW-COMPUTER.md).

In Windows PowerShell (the one that comes with Windows), as your normal user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
winget install --id Git.Git --exact --silent
winget install --id GitHub.cli --exact --silent
```

Close and reopen PowerShell, then:

```powershell
gh auth login
git clone https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git "$env:USERPROFILE\repos\shared-tooling"
& "$env:USERPROFILE\repos\shared-tooling\scripts\Bootstrap-NewComputer.ps1" -RepoUrl https://github.com/<YOUR_GITHUB_USER>/shared-tooling.git
```

Then open a new window, run `claude`, and sign in.

## Old computer, short version

To capture your current configuration into your copy before you switch computers, in
PowerShell:

```powershell
& "$env:USERPROFILE\repos\shared-tooling\scripts\Sync-ClaudeSeat.ps1" -Commit
git -C "$env:USERPROFILE\repos\shared-tooling" push
```

Look at what was captured (`git -C "$env:USERPROFILE\repos\shared-tooling" show --stat`)
before you push. Your copy must stay **private**: the sync copies your Claude Code memory
and your `.gitconfig` (your name and email) into it.

## Rules this kit follows

- No secrets in the repository. The pre-commit hook and the sync script both scan for them.
- Paths use `%USERPROFILE%` or `$env:USERPROFILE`, so nothing depends on your user name.
- The hooks live at the fixed path `C:\Dev\claude-hooks` on every computer, so one
  `settings.json` works everywhere.

## Licence

Released under the [MIT License](LICENSE).
