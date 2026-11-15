#!/usr/bin/env python
"""Tests for context-reminders.py (the PreToolUse advisory/push-confirm hook).

Run:  python hooks/test-context-reminders.py

Covers the two things that break silently:
  1. REGRESSIONS -- the git-push block and the SQL/authoring reminders must
     keep firing exactly as before. This hook is registered on
     Bash|PowerShell, Write|Edit, and mcp__gitnexus__.*, so a bad edit is felt
     immediately across every matcher.
  2. THE DDL TRIGGER GAP -- CREATE/ALTER VIEW|PROC|FUNCTION embedded in a
     .ps1/.py wrapper or a heredoc used to produce NO reminder, because the old
     triggers were only `sqlcmd` / `az sql` / `*.sql`. The authoring rule (don't
     build on an expensive wrapper view) has to reach those cases.
  3. NOISE CONTROL -- documentation is full of prose that says "CREATE VIEW".
     Payload matching must stay silent on .md/.txt/.rst/.csv/.tsv or the
     reminder becomes wallpaper and stops being read.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "context-reminders.py")


def fire(tool_input, tool_name=None, cwd=None):
    """Run the hook and reduce its output to a comparable tag string.

    cwd: the session cwd the harness passes in the payload (used by the
    gitnexus branch-qualifier rule)."""
    payload = {"tool_input": tool_input}
    if tool_name:
        payload["tool_name"] = tool_name
    if cwd:
        payload["cwd"] = cwd
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return "CRASH: " + proc.stderr.strip()[-200:]
    if not proc.stdout.strip():
        return "(silent)"
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    if "permissionDecision" in out:
        return "ASK"
    text = out["additionalContext"]
    tags = []
    if "SQL reminder" in text:
        tags.append("SQL_RULES")
    if "view/proc authoring rule" in text:
        tags.append("AUTHORING")
    if "gitnexus list_repos caveat" in text:
        tags.append("LISTREPOS")
    if "gitnexus branch qualifier" in text:
        tags.append("GNBRANCH")
    return "+".join(tags) or "UNTAGGED"


CASES = [
    # --- regressions: pre-existing behaviour must not move -------------------
    ("push block still fires",
     {"command": "git push origin main"}, "ASK"),
    ("git -C push still fires (no per-seat exemption anymore)",
     {"command": "git -C D:/repos/x push origin main"}, "ASK"),
    ("gh pr create still blocks",
     {"command": "gh pr create --fill"}, "ASK"),
    ("az repos pr create still blocks",
     {"command": "az repos pr create --target-branch main"}, "ASK"),
    ("plain sqlcmd -> SQL rules only",
     {"command": 'sqlcmd -S myserver -Q "select 1"'}, "SQL_RULES"),
    ("az sql -> SQL rules only",
     {"command": "az sql db show -n mydb"}, "SQL_RULES"),
    ("benign command stays silent",
     {"command": "git status"}, "(silent)"),
    ("plain git add stays silent",
     {"command": "git add -A"}, "(silent)"),

    # --- DDL must reach the authoring rule ------------------------------------
    (".sql write containing CREATE VIEW",
     {"file_path": "D:/x/v.sql",
      "content": "CREATE VIEW dbo.Foo AS SELECT 1"},
     "SQL_RULES+AUTHORING"),
    (".sql edit with no DDL keyword -> SQL rules only",
     {"file_path": "D:/x/v.sql", "new_string": "WHERE Deleted = 0"},
     "SQL_RULES"),
    ("CREATE OR ALTER VIEW inside a .ps1 heredoc",
     {"file_path": "D:/x/deploy.ps1",
      "content": "$q=@'\nCREATE OR ALTER VIEW dbo.Bar AS SELECT 1\n'@"},
     "AUTHORING"),
    ("ALTER PROCEDURE inside a .py string",
     {"file_path": "D:/x/m.py",
      "content": "SQL='ALTER PROCEDURE dbo.Baz AS SELECT 1'"},
     "AUTHORING"),
    ("heredoc CREATE PROC with no sqlcmd tell",
     {"command": "psql <<'X'\nCREATE PROC dbo.p AS SELECT 1\nX"},
     "AUTHORING"),
    ("sqlcmd + ALTER VIEW -> both reminders",
     {"command": 'sqlcmd -S s -Q "ALTER VIEW dbo.v AS SELECT 1"'},
     "SQL_RULES+AUTHORING"),
    ("CREATE FUNCTION also counts",
     {"file_path": "D:/x/f.ps1",
      "content": "CREATE FUNCTION dbo.ufnX() RETURNS int AS BEGIN RETURN 1 END"},
     "AUTHORING"),

    # --- noise control -------------------------------------------------------
    ("vault .md discussing CREATE VIEW stays silent",
     {"file_path": "D:/v/Views.md", "content": "You can CREATE VIEW like so"},
     "(silent)"),
    ("inventory .csv row stays silent",
     {"file_path": "D:/v/_inv.csv", "content": "create view,AllOrders"},
     "(silent)"),
    ("CREATE TABLE is not a view/proc",
     {"file_path": "D:/x/a.py", "content": "CREATE TABLE t (id int)"},
     "(silent)"),

    # --- gitnexus list_repos slot trap ----------------------------------------
    # 4-tuples: (name, tool_input, tool_name, want). Matched on tool NAME.
    ("mcp list_repos fires the slot-trap caveat",
     {}, "mcp__gitnexus__list_repos", "LISTREPOS"),
    ("other gitnexus MCP tools stay silent (cwd on main)",
     {"target": "main", "direction": "upstream"}, "mcp__gitnexus__impact",
     "(silent)"),
    ("tool_name Bash does not divert the push block",
     {"command": "git push origin main"}, "Bash", "ASK"),
]


def branch_cases():
    """Fixture repos built from .git/HEAD alone -- no git spawn.
    Yields (name, tool_input, tool_name, cwd, want)."""
    import tempfile
    root = tempfile.mkdtemp(prefix="ctxrem-")

    def repo(name, head, worktree=False):
        d = os.path.join(root, name)
        os.makedirs(d)
        if worktree:
            gd = os.path.join(root, name + "-gitdir")
            os.makedirs(gd)
            with open(os.path.join(gd, "HEAD"), "w") as f:
                f.write(head + "\n")
            with open(os.path.join(d, ".git"), "w") as f:
                f.write("gitdir: " + gd + "\n")
        else:
            os.makedirs(os.path.join(d, ".git"))
            with open(os.path.join(d, ".git", "HEAD"), "w") as f:
                f.write(head + "\n")
        return d

    feat = repo("feat", "ref: refs/heads/feature/sample-change")
    main_ = repo("main", "ref: refs/heads/main")
    detached = repo("detached", "0123456789abcdef0123456789abcdef01234567")
    wt = repo("wt", "ref: refs/heads/wt-123-sample-slug", worktree=True)
    norepo = os.path.join(root, "norepo")
    os.makedirs(norepo)
    impact = {"target": "sample_function", "direction": "upstream", "repo": "x"}
    return [
        ("feature branch, no branch: -> reminder",
         impact, "mcp__gitnexus__impact", feat, "GNBRANCH"),
        ("feature branch, branch: passed -> silent",
         dict(impact, branch="feature/sample-change"), "mcp__gitnexus__impact",
         feat, "(silent)"),
        ("feature branch, detect_changes unqualified -> reminder",
         {"repo": "x"}, "mcp__gitnexus__detect_changes", feat, "GNBRANCH"),
        ("main, no branch: -> silent",
         impact, "mcp__gitnexus__impact", main_, "(silent)"),
        ("detached HEAD -> silent (fail toward quiet)",
         impact, "mcp__gitnexus__impact", detached, "(silent)"),
        ("worktree gitdir pointer on feature branch -> reminder",
         impact, "mcp__gitnexus__impact", wt, "GNBRANCH"),
        ("not a repo -> silent",
         impact, "mcp__gitnexus__impact", norepo, "(silent)"),
        ("list_repos on feature branch still gets ITS caveat",
         {}, "mcp__gitnexus__list_repos", feat, "LISTREPOS"),
    ]


def main():
    failures = 0
    for name, tool_input, tool_name, cwd, want in branch_cases():
        got = fire(tool_input, tool_name, cwd=cwd)
        ok = got == want
        failures += not ok
        print("%-5s %-46s want=%-22s got=%s"
              % ("PASS" if ok else "FAIL", name, want, got))

    for case in CASES:
        if len(case) == 4:
            name, tool_input, tool_name, want = case
        else:
            name, tool_input, want = case
            tool_name = None
        got = fire(tool_input, tool_name)
        ok = got == want
        failures += not ok
        print("%-5s %-46s want=%-22s got=%s"
              % ("PASS" if ok else "FAIL", name, want, got))

    # malformed stdin must never interfere with the tool call
    proc = subprocess.run([sys.executable, HOOK], input="not json",
                          capture_output=True, text=True)
    ok = proc.returncode == 0 and not proc.stdout.strip()
    failures += not ok
    print("%-5s %-46s want=%-22s got=%s"
          % ("PASS" if ok else "FAIL", "malformed stdin -> silent, rc=0",
             "(silent)", "(silent)" if ok else "rc=%s" % proc.returncode))

    total = len(branch_cases()) + len(CASES) + 1
    print("\n%d/%d passed" % (total - failures, total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
