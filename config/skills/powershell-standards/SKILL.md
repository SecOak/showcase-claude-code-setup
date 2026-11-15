---
name: powershell-standards
description: PowerShell scripting standards for all PowerShell work, including scripts that call Microsoft Graph, Exchange Online, or Azure. Use this skill whenever writing, reviewing, refactoring, or debugging any PowerShell code, script, function, or module, even for quick one-liners or snippets, and even if the user does not mention standards or conventions. Also use when choosing between Graph SDK cmdlets and raw REST calls, handling Graph throttling or paging, or designing authentication for automation.
---

# PowerShell Standards

Standards for writing PowerShell that is consistent, pipeline-friendly, and safe to run against production systems. These conventions come from real production automation work: app-only Graph authentication, device and identity automation, Exchange Online management, and cloud infrastructure scripting. Follow them for everything from one-liners to full modules, scaling the ceremony to the size of the task (a quick interactive snippet does not need comment-based help; anything saved to a file does).

## Target runtime

Default to PowerShell 7. Note Windows PowerShell 5.1 compatibility concerns only when the script must run in a 5.1-bound context (GPO-deployed scripts, scheduled tasks on servers without PS7, modules that require 5.1). When 5.1 compatibility matters, avoid PS7-only syntax (ternary operators, null-coalescing `??`, `ForEach-Object -Parallel`) and say so in the script header.

## Authentication

Match the auth model to how the script runs, not to what is convenient:

- **Unattended, scheduled, or toolkit scripts**: app-only authentication via an app registration. Certificate credentials over client secrets whenever possible; secrets expire at inconvenient times and end up in plaintext more often than certs do. Least-privilege application permissions, named explicitly in the script header so a reviewer can verify the app registration matches.
- **Interactive one-off admin tasks**: delegated auth (`Connect-MgGraph -Scopes ...`) with only the scopes the task needs. Do not reuse a high-privilege app registration for something a delegated session can do.

Connection hygiene: check for an existing usable session before connecting (for Graph, inspect `Get-MgContext` and its scopes/auth type), and disconnect in a `finally` block for scripts that established their own connection. Never leave an app-only session dangling in an interactive shell.

Never embed secrets, certificate thumbprint and directory identifier combinations meant to be private, or tokens in script bodies. Take them as parameters, pull from a certificate store, or read from a secure store (SecretManagement). It is fine for a script header comment to document the app registration name/ID it expects.

## Graph access: SDK vs raw REST

The decision is case by case, but the cases have a logic. Make the choice deliberately and be consistent within a single script:

1. **Graph SDK cmdlets** (`Get-MgUser`, etc.) when a cmdlet exists for the operation and behaves predictably. This is the default for common CRUD against v1.0 endpoints. Always use `-All` for collection cmdlets rather than manual paging.
2. **`Invoke-MgGraphRequest`** when the SDK gets in the way: beta endpoints, endpoints without cmdlets, cmdlets with known serialization or paging bugs, `$batch` requests, or when the property casing/typing from SDK models causes friction. This keeps the SDK's auth/session handling while giving raw control over the request. Prefer this over `Invoke-RestMethod` any time a Graph session already exists.
3. **`Invoke-RestMethod` with a manually acquired token** only when the Graph SDK is not loaded at all and pulling it in would be heavier than the task warrants, or when calling non-Graph APIs.

When using raw requests, handle paging explicitly: loop on `@odata.nextLink` until absent, accumulating results. For advanced queries against directory objects (`$count`, `$search`, `$filter` on certain properties), include the `ConsistencyLevel: eventual` header and remember `$count=true` is required for some filters.

For operations touching hundreds of objects or more, use JSON `$batch` requests (20 per batch) instead of sequential calls, and expect throttling (see below).

## Script and function structure

- Verb-Noun names with approved verbs (`Get-Verb` is the authority). Singular nouns.
- `[CmdletBinding()]` on every function and script. Add `SupportsShouldProcess` on anything that changes state (see Safety).
- Param blocks with types, validation attributes (`ValidateNotNullOrEmpty`, `ValidateSet`, `ValidatePattern`), and sensible defaults. Mandatory parameters actually marked `Mandatory`.
- Comment-based help (`.SYNOPSIS`, `.DESCRIPTION`, `.PARAMETER`, `.EXAMPLE`, `.NOTES`) on every saved function and script. `.NOTES` carries author, date, required modules, required permissions/scopes, and the app registration it expects if app-only.
- Functions return objects. Formatting (`Format-Table`, string building for display) happens only at the outermost layer, never inside a function that something else might consume.
- One function does one thing. Scripts that orchestrate should be thin: parameter handling, connect, call functions, export, disconnect.
- `#Requires -Modules` statements for hard dependencies rather than silent assumptions. Check module availability with a clear error message before doing work when `#Requires` is not appropriate.

## Error handling and throttling

- Use `try/catch` with `-ErrorAction Stop` on calls where failure must be handled; do not rely on `$?` inspection or let errors scroll by.
- Decide per failure whether it is fatal or survivable. Fatal (auth failure, missing prerequisite, bad input): `throw` with a message stating what failed and what the operator should check. Survivable (one user of 300 failed to resolve): `Write-Warning` with the identifying detail, record the failure in the results, continue the loop. Batch scripts should finish the batch and report failures, not die at item 37 of 300.
- Graph throttling: catch 429 (and 503/504 for good measure), honor the `Retry-After` header when present, otherwise exponential backoff with jitter. Cap retries (3 to 5) and surface a warning when retrying so long runs are debuggable. Wrap this in a reusable retry helper rather than sprinkling sleep calls.
- Cleanup (disconnect, dispose, remove temp files) lives in `finally`.

## Output and logging

- Emit pipeline-friendly `[PSCustomObject]`s with consistent, deliberately chosen property names. Build the object once with all properties rather than `Add-Member` accretion.
- `Write-Verbose` for progress and diagnostic detail, `Write-Warning` for survivable problems, `Write-Error`/`throw` for real failures. `Write-Host` only for deliberate operator-facing status in interactive tooling, never as a logging mechanism, never inside functions that produce data.
- For long-running batch operations, `Write-Progress` with a counter (`"Processing user 42 of 316"`), plus `Write-Verbose` breadcrumbs.
- Exports: CSV via `Export-Csv -NoTypeInformation` with a timestamped filename convention (`<Noun>-<yyyyMMdd-HHmm>.csv`) and the output path as a parameter with a sane default, written to an explicit report/output directory, never the current directory by assumption.
- Scripts intended for scheduled/unattended runs get a transcript or structured log file with the same timestamp convention.

## Safety on destructive operations

Anything that creates, modifies, or deletes gets `SupportsShouldProcess` with a real `$PSCmdlet.ShouldProcess()` call per item, so `-WhatIf` genuinely previews and `-Confirm` genuinely gates. High-impact operations (deletes, permission changes, mass updates) additionally default to a report-only mode: the script's default behavior is to show what would change, with an explicit switch (`-Apply` or `-Execute`) required to make changes. An organization-wide script that changes things by default is a bug even if the code is correct.

When a script both reads at scale and writes, separate the phases: gather, report the plan, then apply. This makes dry runs natural and failures resumable.

## Review checklist

When reviewing or refactoring existing PowerShell, check in this order: secrets in the body, missing WhatIf support on mutations, unbounded Graph calls without paging or throttling handling, `Write-Host` used as output, functions emitting formatted text, and missing error handling on the calls that matter. Fix structural problems before style.
