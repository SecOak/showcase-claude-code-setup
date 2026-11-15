#!/usr/bin/env python
"""PreToolUse hook: three-tier gate over Azure, ADO, SQL and filesystem operations,
even when a broad `permissions.allow` rule would otherwise auto-run them silently.

DESIGN (three-tier model)
---------------------------------------------------------------------------
An earlier version of this hook was a binary blocklist: silent or hard-block,
decided by `GUARD_HARD_BLOCK`. Testing showed a hook `"ask"` decision DOES beat a
broad `permissions.allow` rule and DOES escalate past the harness's own read-only
classifier -- the premise that produced a pure hard-block design ("ask is inert
under a broad allow rule") was false. That reopened a real middle tier, so this
file implements THREE tiers instead of two:

  * tier 0, silent      -> everything not matched below (reads, routine dev work,
                           repo/PR/pipeline ops, plain `git push`, in-repo
                           writes/deletes).
  * tier 1, ask         -> consequential but recoverable (SQL writes, az infra
                           writes, mutating HTTP, writes/deletes outside the repo
                           root, package installs, git history-rewrite/discard,
                           ...). ALWAYS "ask", in both modes below -- this tier
                           does not escalate to "deny" under GUARD_HARD_BLOCK, by
                           design (an approve path is the point of it).
  * tier 2, hard-block  -> irreversible, kept deliberately SMALL (az delete/purge,
                           SQL DROP/TRUNCATE/DELETE FROM, git force-push/reset
                           --hard/clean -f, a delete whose target is a PROVABLE
                           path outside the repo root, registry/cert-store
                           delete). Decision depends on mode (below).

The tier boundaries were measured against real historical shell-command traffic
and refined case by case; this file's job is to implement that map, not
re-derive the boundaries from first principles.

Why "deny" for tier 2 and not "ask" -- the finding behind this design:
  A hook's `"ask"` does NOT reliably prompt when a `permissions.allow` rule
  matches, and `permissions.ask` RULES lose to `allow` rules too, sometimes.
  Worse, none of that is testable from a session whose `permission_mode` is not
  `default` (e.g. `acceptEdits` auto-approves Bash outright, so "no prompt
  appeared" proves nothing). A hook's **"deny" is different: it beats an allow
  rule AND blocking is observable in every permission mode** -- so tier 2 keeps
  using "deny" (under GUARD_HARD_BLOCK) because it is the one mechanism proven
  to survive every mode and every allow rule -- it is the floor. The "ask is
  inert under a broad allow rule" half of that original reasoning turned out to
  be wrong: an "ask" from this hook was later shown to prompt correctly even
  under a broad allow rule, controlled both directions. So tier 1 below relies
  on hook `"ask"` deliberately and is not theatre; only tier 2 needs "deny"
  specifically, and only because "ask" is proven solely in `default` permission
  mode (anyone routinely in `acceptEdits` still wants an unconditional floor for
  irreversible ops).

WHAT THIS IS -- read before trusting the file name
------------------------------------------------------------------------
This is a BLOCKLIST/ASKLIST over specific, measured shapes -- it allows
everything not enumerated below. It is a seatbelt, not a sandbox: it reduces
accidents and is not a complete defence. Measuring real traffic and
adjudicating the contested shapes case by case is the intended way to extend
it, not guessing at patterns; over-matching prose was the most frequent
failure in practice, see `unquoted()`/`segments()` below.

Override marker: a command may carry the literal token `#GUARD-OK`, which is a
trailing comment in both bash and PowerShell, so it never changes what runs.
It is an explicit, visible operator marker for a reviewed command. The token
only counts OUTSIDE quotes -- see main(); merely naming it in a commit message
used to disarm the guard completely, an invoked-vs-mentioned bug that failed
OPEN. Every use that suppresses a decision is recorded, see AUDITING below.

AUDITING -- why this file writes a log
---------------------------------------------------
The property to guarantee for an override is that it is *undeniable*: every use
leaves a trace that outlives the transcript.

A hook `deny` SURVIVES `--permission-mode bypassPermissions` (tested with a
canary target outside the repo root), and a hook `deny` was previously never
recorded anywhere. Denials and overrides were both invisible. One
append-on-use log closes both halves.

Exactly two events are recorded -- `override` (a `#GUARD-OK` that actually
suppressed a decision) and `deny` (a tier-2 hard block). Tier-1 `ask` is
deliberately NOT logged: the user sees every one of those in the moment, and
there are many, so logging them would bury the two events nobody can see today
under the ones everybody already does. A `#GUARD-OK` on a command the guard was
never going to touch is not an override either -- it is not logged, or the log
would fill with non-events.

Path: `%USERPROFILE%\\.claude\\guard-audit.jsonl`, overridable via
`GUARD_AUDIT_LOG` so the test suite never writes to the real log. Logging is
wrapped so that it can NEVER change what the guard decides -- see audit().

Modes (govern tier 2 ONLY -- tier 1 is always "ask"):
  * default            -> tier 2 gets "ask" (correct for a user with NO broad
                          allow rules -- prompts already work as-is).
  * GUARD_HARD_BLOCK=1 -> tier 2 gets "deny" (for a user carrying a broad
                          allowlist -- "ask" is proven only in `default` mode,
                          so a floor that works in every mode still matters for
                          irreversible ops). Set it in the `env` block of
                          settings.json; the env block hot-reloads, no restart
                          needed.

Scope: the repo root that bounds "safe" writes/deletes defaults to
`%USERPROFILE%\repos`, overridable via `GUARD_REPO_ROOT`. PowerShell PSDrive
delete targets are split by persistence: `Env:`/`Variable:`/`Alias:`/
`Function:` deletes are session-scoped and pass silently, while
`HKLM:`/`HKCU:`/`Cert:`/`WSMan:` deletes stay gated at tier 2.

Deploy target: `C:\\Dev\\claude-hooks\\guard-destructive-azure-sql.py`, invoked as
`python -S -E C:\\Dev\\claude-hooks\\guard-destructive-azure-sql.py`. Edit the copy
in this repo's `hooks\\` directory, then copy it to the deploy path. Re-run
`test-guard-destructive.py` after any edit.
"""
import sys
import json
import re
import os
import datetime

# Command text captured from tool_input can contain non-ASCII. It survives
# cp1252 stdout only because json.dumps escapes it -- an implicit default, not
# a decision. Pin the stream so the guard's block message can never become a
# silent no-op on a narrower codepage. A guard that fails to print is a guard
# off.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Explicit operator override marker for a reviewed command (lowercase for matching).
CONFIRM_TOKEN = "#guard-ok"
HARD_BLOCK = os.environ.get("GUARD_HARD_BLOCK") == "1"

# Append-only audit trail -- see AUDITING in the module docstring. Overridable so
# the test suite (which drives real denies through this file) never writes to the
# real log.
AUDIT_LOG = os.environ.get(
    "GUARD_AUDIT_LOG", os.path.expandvars(r"%USERPROFILE%\.claude\guard-audit.jsonl"))
# Commands are capped so one record is one bounded line: it keeps concurrent
# appends from several live sessions atomic in practice, and keeps the audit
# log readable. `truncated` is recorded when it bites, so the log never
# silently claims to hold a command it only holds the front of.
AUDIT_CMD_MAX = 2000

# The repo root that bounds "safe" writes/deletes below (see _UNDER_REPOS).
# Overridable so a machine with a different repo layout, or the test suite,
# can point this at something else without editing the regex.
REPO_ROOT = os.path.expandvars(os.environ.get("GUARD_REPO_ROOT", r"%USERPROFILE%\repos"))
_REPO_DRIVE, _REPO_REST = os.path.splitdrive(REPO_ROOT)
_REPO_DRIVE_LETTER = (_REPO_DRIVE[:1] or "c").lower()
_REPO_REST_POSIX = re.escape(_REPO_REST.replace("\\", "/").strip("/"))

# A SQL statement can only DO anything if one of these is actually being INVOKED.
SQL_CLIENT = re.compile(
    r'(^|[\s;|&(<>/\\])('
    r'sqlcmd(\.exe)?|invoke-sqlcmd|bcp(\.exe)?|sqlpackage(\.exe)?|'
    r'psql|mysql|mariadb|sqlite3'
    r')\b'
    r'|(^|\s)az\s+sql\b'
)

_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')

# A quoted string in COMMAND POSITION is the executable, not prose -- this host
# really does call `"/c/Program Files/.../sqlcmd.exe" -Q "..."`, and blanking all
# quoted spans would hide it.
_QUOTED_EXE = re.compile(
    r'(^|[\s;|&(])["\'][^"\']*?'
    r'(sqlcmd|invoke-sqlcmd|bcp|sqlpackage|psql|mysql|mariadb|sqlite3)'
    r'(\.exe)?["\']'
)

# --- PowerShell PSDrive delete targets ------------------------------------------
# `Remove-Item Env:\FOO` removes an in-process environment variable, not a file.
# It is session-scoped and trivially reversible, so it is NOT a destructive delete
# -- but an earlier version of this rule blocked it, because no path under the
# repo root is present so it fell through to the fail-safe "unverifiable target"
# branch. That surfaced when the guard blocked the very command being used to
# test the guard; it matters because heavy PowerShell users running under
# GUARD_HARD_BLOCK have no approve button.
#
# No shell / tool_name check is needed to tell these apart from real paths: a colon
# is not legal in an NTFS filename, so `<name>:` in target position is unambiguously
# a PSDrive and can never be a file, in Bash or PowerShell.
#
# The two provider sets are split deliberately by PERSISTENCE, not by syntax:
#   session-scoped (safe)  -> Env:, Variable:, Alias:, Function:  -- vanish anyway
#   persistent (still gated) -> HKLM:/HKCU:/... , Cert:, WSMan:   -- real destruction
_SAFE_PSDRIVE = re.compile(
    r'(?:^|[\s,;=(])(?:env|variable|alias|function):[\\/]?[^\s,;"\'<>|]*'
)
_PERSISTENT_PSDRIVE = re.compile(
    r'(?:^|[\s,;=(])(?:hk(?:lm|cu|cr|u|cc):|cert:|wsman:|registry::)'
)

# A rooted filesystem path, in every form the two shells on this host produce:
#   c:\... / c:/...        Windows, either separator
#   //c/...                Git Bash's double-slash drive form
#   /c/...                 Git Bash's single-slash drive form
#   /cygdrive/c/...        Cygwin-style form
#   \\server\share         UNC
# The drive letter must stand alone: the negative lookbehind stops `env:\foo` from
# yielding a phantom `v:\foo` and `https://x` from yielding `s://x` -- both of which
# used to register as off-repo paths and force a block. (`$env:TEMP\x` still has no
# standalone drive letter, so it stays gated, which is correct: that one really does
# delete a file.)
#
# The POSIX forms were MISSING from an earlier version of this regex, so every
# Bash-tool delete inside the repo root -- e.g. `rm -f /c/repos/...` -- matched no
# rooted path at all and fell into the fail-safe "unverifiable target" branch and
# hard-blocked. Fail-CLOSED, so an annoyance rather than a hole, but it blocked
# routine housekeeping repeatedly.
# The `(?<![\w./])` boundary on the single-slash form is what keeps it from inventing
# phantom paths: without it, `https://host/x/y` yields `/x/y` and `./a/b` yields
# `/a/b`. A phantom matters in BOTH directions -- one that happened to land under
# the repo root would GRANT silence to a real off-repo delete beside it, and one
# that landed elsewhere would block a legitimate call. Pinned by PATTERN_CASES in
# the test.
_ROOTED_PATH = re.compile(
    r'(?:(?<![a-z0-9])[a-z]:[\\/]'
    r'|//[a-z]/'
    r'|(?<![\w./])/(?:cygdrive/)?[a-z]/'
    r'|\\\\)[^\s"\'<>|]*'
)
# Every form above, anchored at the configured repo root (REPO_ROOT / GUARD_REPO_ROOT
# above). The trailing separator is required, so the repos ROOT itself is
# deliberately NOT "under" repos and a delete of it stays gated.
_UNDER_REPOS = re.compile(
    r'^(?:%s:[\\/]%s[\\/]|//%s/%s/|/(?:cygdrive/)?%s/%s/)' % (
        _REPO_DRIVE_LETTER, _REPO_REST_POSIX,
        _REPO_DRIVE_LETTER, _REPO_REST_POSIX,
        _REPO_DRIVE_LETTER, _REPO_REST_POSIX)
)

# Delete verbs, and the statement separators used to isolate the segment a delete
# actually lives in. Note `rd`/`del` etc. are matched with a boundary prefix so a
# word like "hard" or "model" cannot trigger them.
_DELETE_VERB = re.compile(
    r'(^|[\s;|&(])(remove-item|rmdir|rd|del|erase|clear-content|rm)\b'
)
_SEPARATOR = re.compile(r'\|\||&&|[;|&\n]')

# The az/ADO CLI command chain: every word between `az` and the first flag.
# `(?!-)` stops the run at the first `--flag`, so a verb can only be recognised
# in the SUBCOMMAND position and never in an argument value (see the comment in
# hard_block_reason). The prefix class accepts a quote so a quoted invocation
# like `pwsh -c "az group delete ..."` is seen too.
_AZ_CHAIN = re.compile(
    r'(?:^|[\s"\'`])az\s+((?:(?!-)[a-z0-9-]+\s+)*(?!-)[a-z0-9-]+)'
)

# An interpreter handed a command STRING: the quoted span is CODE, not prose.
# This is the discriminator the az seam was missing. Quotes alone cannot tell
#   pwsh -c "az group delete -n rg --yes"        (execution -> must block)
# from
#   git commit -m "...az group delete..."        (prose -> must pass)
# and because the chain scan ran on the raw command to catch the first, it also
# hard-blocked the second. Real cases seen: a commit message documenting cleanup,
# a note recording that finding (so the bug concealed its own evidence), and a
# READ-ONLY grep whose search pattern merely contained the words.
#
# Compare _QUOTED_EXE above: same problem, different shape. That one recognises a
# quoted PATH standing in COMMAND position ("C:\...\sqlcmd.exe" -Q ...); this one
# recognises a quoted ARGUMENT being handed to an interpreter. Both answer "is this
# span going to be executed?" -- which is the only question that separates an
# invocation from a mention.
_SHELL_WRAPPER = re.compile(
    r'(^|[\s;|&(])(pwsh|powershell|bash|sh|zsh|cmd)(\.exe)?\s+[^\n]*?(-c\b|-command\b|/c\b|/k\b)'
)

# --- Tier 1 ("ask") primitives ---------------------------------------------------
# Write verbs whose TARGET matters, scoped the same way as _DELETE_VERB/_ROOTED_PATH/
# _UNDER_REPOS above: consequential only when the target is a PROVABLE path outside
# the repo root. A relative/unverifiable target is left silent here (unlike deletes)
# -- writing a relative filename in the cwd is what nearly every script does, and an
# earlier version's blanket match on these verbs was the single biggest source of
# unnecessary prompts.
_WRITE_VERB = re.compile(
    r'(^|[\s;|&(])(set-content|out-file|rename-item|move-item)\b'
)
_SED_INPLACE = re.compile(r'(^|[\s;|&(])sed\b[^\n]*\s-i\b')

# SQL statements that mutate data/schema but are not the tier-2 DROP/TRUNCATE/DELETE
# FROM/ALTER..DROP shapes above. Same invocation rule as the tier-2 SQL check: the
# CLIENT must appear outside quotes (checked by the caller), the KEYWORDS are matched
# on the raw command since they legitimately live inside `-Q "..."`.
_SQL_WRITE_VERB = re.compile(
    r'\bupdate\s+\w|\binsert\s+into\b|\bexec(?:ute)?\b|\bsp_configure\b|'
    r'\balter\s+(?:table|database|procedure|proc)\b|'
    r'\bcreate\s+(?:table|proc|procedure)\b'
)

# `az <resource> <write-verb>` -- infra writes (privilege escalation, NSG changes,
# secret overwrite, prod resize) as distinct from the ADO repo/PR/pipeline ops that
# stay silent (`az repos|pipelines|artifacts|boards|devops` are NOT in this list).
# The prefix class accepts a quote for the same reason _AZ_CHAIN's does: a real
# `pwsh -c "az keyvault secret set ..."` must be seen. This rule gained that quote
# class only after the same quoted-az hole was found and closed at the tier-2 seam
# above -- so every interpreter-wrapped az infra write had been silent at tier 1 the
# whole time. Adding it is only safe now, because the caller gates on
# _SHELL_WRAPPER and hands prose through unquoted(); before that gate existed, a
# quote class here would have asked on any commit message naming an az write.
_AZ_INFRA_RESOURCE = re.compile(
    r'(^|[\s"\'`])az\s+(vm|aks|webapp|functionapp|containerapp|sql|storage|keyvault|'
    r'network|role|group|deployment|monitor|identity|acr|redis|servicebus|'
    r'eventhub|staticwebapp|cosmosdb|ad|resource)\b'
)
# The audited silent mutators below now ask (extend, not invert, an earlier
# ruling): the 9 silent mutators found in an audit pass, plus `move` (for
# `az resource move`; `resource` is the generic mutator for any type and was
# missing from the resource list above).
_AZ_WRITE_VERB = re.compile(
    r'\b(create|update|set|add|assign|reset|restart|stop|start|deallocate|'
    r'scale|import|restore|resize|swap|invoke|upgrade|detach|renew|redeploy|'
    r'generalize|approve|move)\b'
)

_MUTATING_HTTP = re.compile(
    r'\bcurl\b[^;|&\n]*(-x\s*(post|put|delete|patch)\b|--data\b|\s-d\s)'
    r'|\binvoke-(?:restmethod|webrequest)\b[^;|&\n]*-method\s+(post|put|delete|patch)\b'
    r'|\baz\s+rest\b[^;|&\n]*--method\s+(post|put|delete|patch)\b'
)

_GIT_DISCARD = re.compile(
    r'checkout\s+--(\s|$)|\brestore\b|stash\s+(drop|clear)\b'
)
# Anchored to "git <subcommand>", not a bare keyword -- `git pull --rebase` (a
# common, routine sync pattern) contains the word "rebase" as a FLAG, not the
# `git rebase` subcommand, and must stay silent. An earlier, unanchored
# `\brebase\b` misclassified plain `git pull --rebase` calls as history-rewrite
# asks.
_GIT_HISTORY_REWRITE = re.compile(
    r'\bgit\s+(rebase\b|filter-branch\b|commit\s+--amend\b)'
)
_GIT_BRANCH_D = re.compile(r'branch\s+-d\b')

_PKG_INSTALL = re.compile(r'\b(npm|pip3?)\s+(install|update|uninstall)\b')
_ENV_VAR_PERSIST = re.compile(r'setenvironmentvariable')
_ICACLS_GRANT = re.compile(r'\bicacls\b[^;|&\n]*(/grant|/deny|/setowner)\b')
_CHMOD_CHOWN_R = re.compile(r'\b(chmod|chown)\s+-r\b')
_SERVICE_CONTROL = re.compile(r'\b(stop|start|restart)-service\b')
_LOCALUSER_WRITE = re.compile(r'\b(disable|enable|set|remove|new)-localuser\b')
_SCHTASKS_WRITE = re.compile(r'\bschtasks\b[^;|&\n]*/(create|change|delete|run|end)\b')
_REGISTRY_WRITE = re.compile(r'\b(set|new|remove)-itemproperty\b|\breg\s+add\b')


def unquoted(lc):
    """The command with the contents of quoted spans blanked out.

    Used for detecting whether a SQL client is genuinely being invoked, as opposed
    to merely appearing inside a string. The destructive SQL KEYWORDS are matched
    against the full command (they legitimately live inside `-Q "..."`), but the
    CLIENT must appear outside quotes to count as an invocation. This is what
    separates `sqlcmd -Q "DROP TABLE x"` (execution -> block) from
    `git commit -m "guard now catches DROP TABLE inside sqlcmd strings"` (prose ->
    allow).
    """
    return _QUOTED.sub(lambda m: " " * len(m.group(0)), lc)


def segments(lc):
    """Split a command into statement segments, ignoring separators inside quotes.

    `unquoted()` replaces each quoted span with an equal-length run of spaces, so
    offsets found in the masked copy index straight back into `lc`. That is what
    keeps a `;` or `|` inside a commit message from splitting the command.

    Used to scope the delete rule's path check to the segment the delete actually
    lives in. Before an earlier fix the check ran over the WHOLE command and
    required every rooted path in it to be under the repo root -- so a path
    merely being READ in an unrelated segment forced a block, even when the
    delete target was a provably safe session-scoped `Env:` drive. It blocked
    routine cleanup scripts and this guard's own coverage test.
    """
    mask = unquoted(lc)
    out, start = [], 0
    for m in _SEPARATOR.finditer(mask):
        out.append(lc[start:m.start()])
        start = m.end()
    out.append(lc[start:])
    return out


def delete_status(lc):
    """Classify delete-shaped segments in the command.

    Returns None if no delete verb is present or the delete is confined to
    the repo root / a session-scoped PSDrive (both silent). Otherwise returns a
    (reason, tier) pair:
      tier 2 -- a persistent-PSDrive delete, or a delete with a PROVABLE
                rooted path outside the repo root. We can SEE the target and it
                is genuinely off-repo: irreversible, hard-block eligible.
      tier 1 -- no provable rooted path at all (relative/wildcard/variable/
                piped target). This is a DELIBERATE LOOSENING from an earlier
                fail-safe hard-block -- that older behaviour blocked routine
                cleanup scripts and this hook's own coverage test, with no
                approve path to offer. Tier 1 offers one.

    Scoped to the delete's own segment(s), same reasoning as the old
    destructive_reason(): a path merely read elsewhere in a compound command
    must not affect what is being destroyed. See segments().
    """
    delete_segs = [s for s in segments(lc) if _DELETE_VERB.search(unquoted(s))]
    if not delete_segs:
        return None

    # The delete segments are unioned rather than judged one by one: either
    # way a single off-repo target denies the call.
    scope = " ".join(delete_segs)

    # Persistent providers are checked FIRST and unconditionally, so a
    # session-scoped target elsewhere in the same command can never mask them.
    if _PERSISTENT_PSDRIVE.search(scope):
        return ("registry / certificate-store delete (persistent PSDrive)", 2)

    rooted = _ROOTED_PATH.findall(scope)
    safe_psdrive = _SAFE_PSDRIVE.findall(scope)
    # Silent only when we can actually SEE what is being deleted AND every
    # filesystem target is under the repo root. A session-scoped PSDrive target
    # counts as "seen" but grants nothing to the paths beside it -- so
    # `Remove-Item Env:\FOO, C:\Windows\x` is still gated on the C: path.
    if (rooted or safe_psdrive) and all(_UNDER_REPOS.match(p) for p in rooted):
        return None

    if rooted:
        return ("destructive file delete outside the repo root", 2)

    return ("delete target not provably under the repo root "
            "(relative/wildcard/piped)", 1)


# --- session-scoped SQL throwaways are not irreversible. -----------------------
# A `#temp` table dies with the connection, a `##global` temp with its last session, a
# `@table` variable with the batch -- so DROP/TRUNCATE/DELETE aimed ONLY at those has
# nothing to protect, and blocking it taught operators to route around the guard.
# The exemption is target-parsed and FAILS TOWARD BLOCKING: any target that is not
# provably a temp object -- including an unparseable list or a mixed
# `#tmp, dbo.Real` -- still blocks.
_TEMP_SQL_OBJECT = re.compile(r'^(\[?tempdb\]?\s*\.\.\s*)?\[?#{1,2}[\w$]+\]?$')
_TABLE_VAR_OR_TEMP = re.compile(r'^(@\w+|(\[?tempdb\]?\s*\.\.\s*)?\[?#{1,2}[\w$]+\]?)$')


def _all_temp_tables(target_list):
    targets = [t.strip().strip('"\'`') for t in target_list.split(',')]
    return bool(targets) and all(t and _TEMP_SQL_OBJECT.match(t) for t in targets)


def _sql_drop_table_blocks(lc):
    """True when a DROP TABLE names anything beyond session-scoped temp objects."""
    hit = False
    for m in re.finditer(r'\bdrop\s+table\s+(?:if\s+exists\s+)?([^;"\']*)', lc):
        hit = True
        if not _all_temp_tables(m.group(1)):
            return True
    # A `drop table` the target parse cannot see at all -> block, never guess.
    return bool(re.search(r'\bdrop\s+table\b', lc)) and not hit


def _sql_truncate_blocks(lc):
    hit = False
    for m in re.finditer(r'\btruncate\s+table\s+([^;"\'\s]*)', lc):
        hit = True
        t = m.group(1).strip().strip('"\'`')
        if not (t and _TEMP_SQL_OBJECT.match(t)):
            return True
    return bool(re.search(r'\btruncate\s+table\b', lc)) and not hit


def _sql_delete_from_blocks(lc):
    hit = False
    for m in re.finditer(r'\bdelete\s+from\s+([^;"\'\s]*)', lc):
        hit = True
        t = m.group(1).strip().strip('"\'`')
        if not (t and _TABLE_VAR_OR_TEMP.match(t)):
            return True
    return bool(re.search(r'\bdelete\s+from\b', lc)) and not hit


def hard_block_reason(lc):
    """Return a tier-2 (irreversible, hard-block-eligible) reason, else None.

    Runs on the whole LOWERCASED command, which is why it catches SQL buried in
    `sqlcmd -Q "..."` and is immune to DROP/drop casing -- permission rules are
    case-SENSITIVE and cannot look inside a quoted string at all.

    Kept deliberately SMALL -- everything recoverable lives in ask_reason()
    instead, including `git branch -D` and an unverifiable delete target, both
    formerly hard-blocked here.
    """
    # --- Azure CLI / Azure DevOps destructive verbs ---
    # The verb counts only in the az COMMAND CHAIN -- the words between `az` and
    # the first flag -- never inside an argument VALUE. Scanning the whole
    # command hard-blocked an ADDITIVE `az repos pr create` (once on "DELETE" in
    # a --description, once on "remove" in a --title); that is the same prose
    # false-positive the SQL branch below fixes, never applied at this seam.
    #
    # The seam is closed from the other side too. An earlier version of this
    # scan ran on the RAW command so that a quoted invocation
    # (`pwsh -c "az group delete ..."`) was still caught; the price was that any
    # PROSE naming an az delete hard-blocked. Quotes were the wrong
    # discriminator: what makes a quoted span dangerous is that an INTERPRETER
    # will execute it. So scan the raw command only when a shell wrapper is
    # present, and the quote-blanked copy otherwise. Both the real-invocation
    # hole and the prose false positives stay closed -- see the paired deny and
    # silent cases in test-guard-destructive.py.
    #
    # One more case: the wrapper itself must be OUTSIDE quotes to count. A real
    # invocation always is (`pwsh -c "..."` -- the interpreter and flag are never
    # inside the payload), while prose QUOTING an invocation carries it inside a
    # quoted span (`git commit -m 'guard: pwsh -c "az group delete" now blocks'`
    # -- the self-concealing shape: documenting guard work tripped the guard).
    # Searching the wrapper on unquoted(lc) separates the two. Fails toward
    # blocking: _QUOTED is not escape-aware, so a same-quote-escaped nesting can
    # leave fragments visible and still deny -- narrower false positive, never a new hole. This
    # change did not alter which wrapper spellings are recognised, so nothing that
    # blocked before stops blocking.
    az_text = lc if _SHELL_WRAPPER.search(unquoted(lc)) else unquoted(lc)
    for chain in _AZ_CHAIN.findall(az_text):
        if re.search(r'\b(delete|purge)\b', chain):
            return "Azure/ADO CLI delete/purge"
        if re.search(r'\bremove\b', chain):
            return "Azure/ADO CLI remove"
    if re.search(r'(?:^|[\s"\'`])az\s+account\s+clear\b', az_text):
        return "az account clear"

    # --- SQL destructive statements, incl. buried inside `sqlcmd -Q "..."` ---
    # ONLY when a SQL CLIENT is actually being invoked. SQL cannot execute without
    # one, and scanning every command for SQL keywords produces constant false
    # positives on prose -- a `git commit -m "...DROP TABLE..."` would be blocked
    # otherwise, and commit messages and docs discuss SQL often.
    # The hook inspects the command string it is given, not file contents, so
    # this branch scans statements that appear on the command line itself.
    if SQL_CLIENT.search(unquoted(lc)) or _QUOTED_EXE.search(lc):
        # Non-table object kinds are never session-scoped -- unconditional. TABLE
        # goes through the temp-target parse (helpers above).
        if re.search(r'\bdrop\s+(database|schema|view|index|procedure|'
                     r'proc|function|login|user|role|trigger|sequence)\b', lc):
            return "SQL DROP"
        if _sql_drop_table_blocks(lc):
            return "SQL DROP"
        if _sql_truncate_blocks(lc):
            return "SQL TRUNCATE TABLE"
        if _sql_delete_from_blocks(lc):
            return "SQL DELETE FROM"
        if re.search(r'\balter\b.*\bdrop\b', lc):
            return "SQL ALTER ... DROP"

    # --- git operations that rewrite published history or discard work ---
    # (a normal `git push` is NOT here -- that must stay usable. `git branch -D`
    #  is NOT here either -- demoted to tier 1, recoverable from the reflog.)
    if re.search(r'(^|[\s;|&(])git\b', lc):
        # `push` must be the git subcommand, not the head of a hyphenated word.
        # `\b` matches between "push" and "-", so a bare `push\b` also matched
        # PowerShell's `Push-Location`; combined with the format operator's ` -f`
        # that hard-blocked ordinary read-only commands, recovered verbatim from
        # the audit log. The lookarounds fix it WITHOUT anchoring to `git\s+push`,
        # which would have stopped catching `git -C <repo> push --force` -- a
        # form worth preferring since it needs no `cd`.
        # The force flag must sit in the SAME command segment as `push`: a force
        # flag is an argument to the push itself, so it can never cross `;`/`|`/`&`
        # or a newline. An earlier, unscoped `.*` here paired
        # `git push origin main; ... ("{0}" -f $x)` as a force-push.
        if re.search(r'(?<![-\w])push(?![-\w])[^;|&\n]*'
                     r'(--force\b|--force-with-lease\b|\s-f\b)', lc):
            return "git force-push (rewrites remote/ADO history)"
        if re.search(r'reset\s+--hard\b', lc):
            return "git reset --hard (discards uncommitted work)"
        if re.search(r'clean\s+-[a-z]*f', lc):
            return "git clean -f (deletes untracked files)"

    # --- find that deletes (no permission rule can see the -delete flag) ---
    if re.search(r'(^|[\s;|&(])find\b', lc) and (
        re.search(r'\s-delete\b', lc) or re.search(r'-exec\s+rm\b', lc)
    ):
        return "find -delete / -exec rm"

    # --- Destructive filesystem deletes NOT confined to the repo root (any shell) ---
    # The VERB must appear OUTSIDE quotes to count as an invocation -- exactly the
    # rule already applied to SQL clients above, and for the same reason. Matching
    # the raw string blocked this hook's own fix commit, whose message contained
    # the words `Remove-Item ... C:\Windows`. Commit messages and docs discuss
    # destructive commands constantly, so a rule that fires on prose fires all day
    # -- and now hard-BLOCKS rather than prompting.
    # Only the PROVABLE-off-repo branch is tier 2; the unverifiable-target branch
    # is tier 1, see ask_reason().
    status = delete_status(lc)
    if status and status[1] == 2:
        return status[0]

    return None


def ask_reason(lc):
    """Return a tier-1 (consequential, recoverable) reason, else None.

    Only called when hard_block_reason() found nothing -- see main(). Always
    maps to permissionDecision "ask", in BOTH modes; GUARD_HARD_BLOCK affects
    tier 2 only.
    """
    # An unverifiable delete target (no provable rooted path) is a deliberate
    # loosening from hard-block to ask, not a hard block.
    status = delete_status(lc)
    if status and status[1] == 1:
        return status[0]

    # SQL write/exec via a genuinely invoked client -- same invocation check
    # as the tier-2 SQL DROP/TRUNCATE/DELETE FROM rule.
    if SQL_CLIENT.search(unquoted(lc)) or _QUOTED_EXE.search(lc):
        if _SQL_WRITE_VERB.search(lc):
            return "SQL write/exec (UPDATE/INSERT/EXEC/ALTER/CREATE)"

    # az infra writes -- excludes ADO repo/pipeline/boards ops (those stay silent;
    # they are not in _AZ_INFRA_RESOURCE) and excludes delete/purge/remove (tier 2,
    # already returned by hard_block_reason before this function runs).
    #
    # Same seam as the tier-2 az scan above -- one defect can appear at several
    # seams, so fixing one and stopping leaves the class alive.
    # `_AZ_INFRA_RESOURCE` is prefixed `(^|\s)az\s+`, and a space inside a quoted
    # string is still a space, so `git commit -m "notes on az keyvault secret set
    # rotation"` used to ask. Same discriminator applies here: an interpreter
    # makes a quoted span code. The wrapper counts only OUTSIDE quotes -- see the
    # tier-2 az scan above for the full reasoning.
    az_ask_text = lc if _SHELL_WRAPPER.search(unquoted(lc)) else unquoted(lc)
    if _AZ_INFRA_RESOURCE.search(az_ask_text) and _AZ_WRITE_VERB.search(az_ask_text):
        return "az infra write (create/update/set/restart/stop/scale/...)"

    # Mutating HTTP -- outbound writes to Graph/M365/whatever the endpoint is;
    # also the standing "never send anything without my confirmation" rule.
    if _MUTATING_HTTP.search(lc):
        return "mutating HTTP call (POST/PUT/DELETE/PATCH)"

    if re.search(r'(^|[\s;|&(])git\b', lc):
        if _GIT_DISCARD.search(lc):
            return "git checkout --/restore/stash drop (discards uncommitted work)"
        if _GIT_HISTORY_REWRITE.search(lc):
            return "git rebase/filter-branch/commit --amend (rewrites history)"
        if _GIT_BRANCH_D.search(lc):
            return "git branch -D (force branch delete -- recoverable)"

    if _PKG_INSTALL.search(lc):
        return "npm/pip install|update|uninstall (supply-chain risk)"

    if _ENV_VAR_PERSIST.search(lc):
        return "[Environment]::SetEnvironmentVariable (persistent User env var)"

    if _ICACLS_GRANT.search(lc):
        return "icacls /grant|/deny|/setowner"

    if _CHMOD_CHOWN_R.search(lc):
        return "chmod/chown -R"

    if _SERVICE_CONTROL.search(lc):
        return "Stop/Start/Restart-Service"

    if _LOCALUSER_WRITE.search(lc):
        return "*-LocalUser write"

    if _SCHTASKS_WRITE.search(lc):
        return "schtasks /create|/change|/delete"

    if _REGISTRY_WRITE.search(lc):
        return "registry write (Set-ItemProperty/reg add)"

    # Writes to a path OUTSIDE the repo root -- how hooks, settings and other
    # config files get rewritten. Scoped to the write's own segment(s), same
    # reasoning as delete_status(): a path merely read elsewhere must not count.
    # Silent (not ask) when no rooted path is found at all -- a relative write
    # target is the overwhelmingly common, benign case (an earlier version's
    # biggest false-positive source was matching these verbs unconditionally).
    write_segs = [s for s in segments(lc)
                  if _WRITE_VERB.search(unquoted(s)) or _SED_INPLACE.search(unquoted(s))]
    if write_segs:
        scope = " ".join(write_segs)
        rooted = _ROOTED_PATH.findall(scope)
        if rooted and not all(_UNDER_REPOS.match(p) for p in rooted):
            return "write outside the repo root (Set-Content/Out-File/Rename-Item/Move-Item/sed -i)"

    return None


def audit(event, tier, rule, cmd, data):
    """Append one JSONL record to AUDIT_LOG. Never raises, never blocks.

    The bare `except` is the point, not laziness: this runs inside a PreToolUse
    hook that has already decided what to do. A full disk, a locked file or a
    missing log directory must not turn a "deny" into a crash, and a crashing
    hook is a hook people switch off. Losing an audit line is strictly better
    than changing the guard's verdict -- so the log is best-effort by
    construction.
    """
    try:
        text = cmd if len(cmd) <= AUDIT_CMD_MAX else cmd[:AUDIT_CMD_MAX]
        rec = {
            "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": os.environ.get("USERNAME", ""),
            "session": str(data.get("session_id") or "")[:8],
            "event": event,
            "tier": tier,
            "rule": rule,
            "cmd": text,
        }
        if len(text) < len(cmd):
            rec["truncated"] = len(cmd)
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# The permission surface guards itself. A session that can write settings.json
# can widen its own allow list or deregister this very hook, and the only prior
# control was the auto-mode classifier -- a per-action judgment, active only in
# auto mode. This is the standing mechanism instead.
# Scope: LIVE surfaces only -- a file literally named settings.json /
# settings.local.json directly under a claude-config dir, one seat-dir below it,
# or under a .claude dir. A repo's own settings.template.json is repo SOURCE, not
# a live surface -- free.
# The pattern below matches the path of a live settings file, for the Write, Edit
# and NotebookEdit tools handled by settings_surface_reason().
_SETTINGS_SURFACE = re.compile(
    r'(?i)(?:^|[\\/])(?:\.claude|claude-config(?:[\\/][^\\/]+)?)[\\/]'
    r'settings(?:\.local)?\.json$'
)


def settings_surface_reason(data):
    """Return an ask-reason when a Write/Edit/NotebookEdit targets a live
    Claude settings file, else None. 'ask' in BOTH modes, deliberately, not
    deny: a user-requested edit costs one approval click; a self-escalation
    needs the user's explicit yes. A hook 'ask' escalates past every allow
    rule and survives bypassPermissions, so this is a real interlock where
    Write()/Edit permission RULES are measured inert."""
    if data.get("tool_name") not in ("Write", "Edit", "NotebookEdit"):
        return None
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if path and _SETTINGS_SURFACE.search(path):
        return path
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input -> don't interfere

    # File-tool calls carry no command string; the ONE rule that applies to them
    # is the settings-surface interlock, then they are not this guard's business.
    surface = settings_surface_reason(data)
    if surface:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    "Write to a LIVE Claude permission surface (%s). Claude changes "
                    "permission rules only when the user asked for that specific "
                    "change in this conversation -- confirm." % surface),
            }
        }))
        return

    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return

    lc = cmd.lower()

    # Explicit, visible, per-call override. The token must be INVOKED as a trailing
    # shell comment, not merely MENTIONED inside a string: matching the raw command
    # meant any commit message, doc string or echo naming `#GUARD-OK` disarmed the
    # guard entirely -- and this token gets discussed constantly in commits and
    # docs about the guard itself. Unlike the other invoked-vs-mentioned bugs this
    # file guards against, this one failed OPEN -- a real `az group delete` could
    # ride through on an unrelated commit message.
    if CONFIRM_TOKEN in unquoted(lc):
        # Work out what the override actually suppressed before standing down. The
        # reason is the whole value of the record -- "someone typed #GUARD-OK" is
        # not auditable, "someone overrode a SQL DROP" is. Computing it here also
        # means a token riding along on a command the guard would have passed
        # anyway is silently ignored rather than logged as an override.
        suppressed = hard_block_reason(lc)
        tier = 2
        if not suppressed:
            suppressed = ask_reason(lc)
            tier = 1
        if suppressed:
            audit("override", tier, suppressed, cmd, data)
        return

    # Tier 2 first: irreversible, kept small. Its decision depends on mode.
    reason = hard_block_reason(lc)
    if reason:
        if HARD_BLOCK:
            decision = "deny"
            detail = ("BLOCKED: destructive/irreversible operation (%s). An allow rule "
                      "would otherwise have run this silently. If this is genuinely "
                      "intended, get the user's explicit OK and re-run with "
                      "`#GUARD-OK` appended." % reason)
            audit("deny", 2, reason, cmd, data)
        else:
            decision = "ask"
            detail = ("Destructive/irreversible operation detected (%s). Confirm "
                      "before running." % reason)
    else:
        # Tier 1: consequential but recoverable. Always "ask", in both modes --
        # this is the middle tier that GUARD_HARD_BLOCK users previously had no
        # access to (a hook "ask" does escalate past a broad allow rule after
        # all).
        reason = ask_reason(lc)
        if not reason:
            return  # safe -> silent, normal flow (broad allow rules keep it prompt-free)
        decision = "ask"
        detail = ("Consequential operation detected (%s). Confirm before running."
                  % reason)

    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": detail,
        }
    }))


if __name__ == "__main__":
    main()
