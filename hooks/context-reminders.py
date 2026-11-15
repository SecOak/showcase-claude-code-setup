#!/usr/bin/env python
"""PreToolUse hook: surgical, event-triggered reminders + push confirmation.

Reads the tool-call JSON on stdin. Fires ONLY when the specific command/file
pattern is present, so it costs ZERO always-on context (unlike prose in
CLAUDE.md). Two behaviours:

  1. BLOCK (permissionDecision "ask"): `git push` / `gh pr create` -- enforces
     the rule "ask before pushing" even if the broad allowlist would
     auto-run it.
  2. ADVISE (additionalContext, non-blocking): inject the relevant "I taught you
     this before" reflex only when the matching command/file appears:
       - sqlcmd / *.sql edits            -> generic SQL-file reminders (confirm
         environment/instance before running DDL/DML; SNAPSHOT/locking
         assumptions vary by server, don't assume).
       - CREATE/ALTER VIEW|PROC|FUNCTION -> the view/proc authoring rule (don't
         build new objects on top of an expensive wrapper view when the
         underlying tables are cheap). Matched against the COMMAND TEXT *and*
         the Write/Edit payload, because the sqlcmd/.sql triggers above miss
         DDL embedded in a .ps1/.py or in a heredoc that never says sqlcmd.
       - gitnexus list_repos             -> the commitsBehind slot-trap caveat.
       - other gitnexus MCP tools        -> the `branch:` qualifier reminder.

Only ONE result is emitted per call (first match wins; push-confirm first).
Safe/unmatched commands produce no output -> normal silent flow.

Wire under hooks.PreToolUse for matchers "Bash|PowerShell" AND "Write|Edit"
AND "mcp__gitnexus__.*".
"""
import os
import sys
import json
import re

# Hooks can get a non-UTF-8 stdout on some platforms, and a UnicodeEncodeError
# here would be swallowed into a silent no-op. json.dumps escapes non-ASCII so
# the JSON paths are safe today, but any future plain print() would not be.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def emit_ask(reason):
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))


def emit_context(text):
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


SQL_RULES = (
    "[SQL reminder] Confirm which server/instance and which database you are "
    "about to run this against before executing -- environments are easy to "
    "confuse when a name is reused across prod/test. Don't assume isolation "
    "level, locking hints, or index-build options that worked on one server "
    "carry over to another; check the target's edition/settings first."
)
VIEW_AUTHORING_RULE = (
    "[view/proc authoring rule] Do NOT build a NEW view or proc on top of an "
    "expensive wrapper view when the same data is available cheaply from the "
    "underlying tables -- a wide multi-table wrapper view often materializes "
    "the whole join before your predicate applies, even when you only need a "
    "small slice of it. For EXISTING views/procs you ARE allowed to rewrite "
    "onto the underlying tables where it makes sense -- pre-approved, not "
    "scope creep."
)
LIST_REPOS_RULE = (
    "[gitnexus list_repos caveat] In this result, staleness.commitsBehind "
    "describes a PRIMARY-BRANCH SLOT, not the checked-out branch. On a repo "
    "sitting on a feature/non-main branch, or freshly pulled, it can read "
    "large and WRONG. Do NOT surface or file these numbers as repo or index "
    "staleness. Branch-aware truth: `gitnexus status` in the repo root, or "
    "`git rev-list --count HEAD..origin/<branch>`."
)
GITNEXUS_BRANCH_RULE = (
    "[gitnexus branch qualifier] This repo is checked out on a NON-DEFAULT "
    "branch and the call carries no `branch:`. Unqualified, the gitnexus MCP "
    "tools query the primary-branch index and return `Target 'x' not found` / "
    "`impactedCount: 0` / `risk: UNKNOWN` for anything that exists only on "
    "this branch -- which reads exactly like a stale index. Pass "
    "`branch: <current branch>` alongside `repo:`, and read 'not found' as "
    "WRONG/UNQUALIFIED BRANCH before you read it as stale."
)

# Quoted spans are prose, not invocation -- the invoked-vs-mentioned distinction
# the guard hook learned the hard way. Blanking them keeps a commit message that
# DISCUSSES a flag from firing the wrong rule. The DDL rules deliberately search
# quoted text too, because DDL lives inside quotes.
_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')

# CREATE / CREATE OR ALTER / ALTER of a view, proc, or function. Deliberately
# matched against the Write/Edit payload too -- DDL routinely lands in a .ps1 or
# .py wrapper that never mentions sqlcmd, which the triggers below would miss.
DDL_RE = re.compile(
    r'\b(?:create|alter)\s+(?:or\s+alter\s+)?'
    r'(?:view|proc(?:edure)?|function)\b',
    re.IGNORECASE,
)
# Prose files discuss DDL constantly. Fire the payload match only where the
# text could plausibly BE the DDL, never in documentation.
PROSE_SUFFIXES = ('.md', '.txt', '.rst', '.csv', '.tsv')

DEFAULT_BRANCHES = {'main', 'master'}


def current_branch(cwd):
    """Branch name from .git/HEAD, or None (detached, not a repo, unreadable).

    Reads the file rather than spawning git: this runs on every gitnexus MCP
    call. Follows a worktree's `gitdir:` pointer one hop."""
    try:
        dotgit = os.path.join(cwd, '.git')
        if os.path.isfile(dotgit):  # worktree: ".git" is a pointer file
            with open(dotgit, encoding='utf-8', errors='replace') as f:
                line = f.read().strip()
            if not line.startswith('gitdir:'):
                return None
            dotgit = line[len('gitdir:'):].strip()
        with open(os.path.join(dotgit, 'HEAD'), encoding='utf-8', errors='replace') as f:
            head = f.read().strip()
        prefix = 'ref: refs/heads/'
        return head[len(prefix):] if head.startswith(prefix) else None
    except Exception:
        return None


# Push-confirm: a single strict rule for every user, matched whether or not the
# command uses `git -C <repo> push` (the `-C <path>` form sits between the
# tokens, so an anchored `git push` alone would miss it).
PUSH_RE = re.compile(r'(^|[\s;|&(])git\s+(?:-c\s+\S+\s+)?push\b')


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input -> don't interfere

    # MCP-tool dispatch (matched by tool NAME, not command text). Wired under its
    # own matcher; an MCP call carries no "command", so none of the text rules
    # below can interfere.
    tool_name = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if tool_name == "mcp__gitnexus__list_repos":
        emit_context(LIST_REPOS_RULE)
        return
    if tool_name.startswith("mcp__gitnexus__"):
        # Fires only when the repo is on a non-default branch AND the call is
        # unqualified. On main, or when `branch:` is passed, silent.
        # Fail direction: unreadable HEAD -> None -> silent (no nag outside a repo).
        if not ti.get("branch"):
            branch = current_branch(data.get("cwd") or os.getcwd())
            if branch and branch not in DEFAULT_BRANCHES:
                emit_context(GITNEXUS_BRANCH_RULE)
        return

    cmd = ti.get("command") or ""
    fpath = ti.get("file_path") or ""
    # Write puts the body in "content"; Edit puts the incoming text in "new_string".
    payload = ti.get("content") or ti.get("new_string") or ""
    lc = cmd.lower()
    flc = fpath.lower()

    unquoted_cmd = _QUOTED.sub(' ', lc)

    # 1. BLOCK: confirm before pushing / opening a PR (outward-facing).
    if PUSH_RE.search(lc) or \
       re.search(r'(^|[\s;|&(])gh\s+pr\s+create\b', lc) or \
       re.search(r'(^|[\s;|&(])az\s+repos\s+pr\s+create\b', lc):
        emit_ask("Outward-facing push/PR -- confirm with the user before "
                 "pushing. Approve to proceed.")
        return

    # 2. ADVISE (non-blocking additionalContext), first match wins.
    sql_ctx = ('sqlcmd' in lc
               or re.search(r'(^|[\s;|&(])az\s+sql\b', lc) is not None
               or flc.endswith('.sql'))
    # A .sql file IS the DDL even when only a fragment is being edited, so search
    # the command text and the payload; suppress on prose files (see PROSE_SUFFIXES).
    is_ddl = (DDL_RE.search(cmd) is not None
              or (not flc.endswith(PROSE_SUFFIXES)
                  and DDL_RE.search(payload) is not None))

    if sql_ctx and is_ddl:
        emit_context(SQL_RULES + "\n\n" + VIEW_AUTHORING_RULE)
        return
    if sql_ctx:
        emit_context(SQL_RULES)
        return
    if is_ddl:
        # DDL with no SQL-tooling tell -- e.g. CREATE VIEW inside a .ps1 heredoc.
        emit_context(VIEW_AUTHORING_RULE)
        return


if __name__ == "__main__":
    main()
