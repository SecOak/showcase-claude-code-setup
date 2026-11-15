"""Pipe-test guard-destructive-azure-sql.py (three-tier design).

expected in {"deny","ask","silent"}. "ask" now covers TWO distinct tiers that
this end-to-end harness cannot tell apart by outcome alone (both print "ask"):
tier 2 destructive ops running in soft/default mode (hard=0), and tier 1
consequential-but-recoverable ops in EITHER mode (hard=0 or hard=1) -- tier 1
never escalates to "deny" under GUARD_HARD_BLOCK, by design. Where the
distinction matters, cases are run at hard=1 specifically to prove tier 1
does NOT escalate (a tier-2 case would flip to "deny" at hard=1; a tier-1
case stays "ask").
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

# Defaults to the REPOSITORY copy, next to this test file -- that is the copy
# under active development, so that is what a bare run should verify.
# Overridable via GUARD_HOOK so a DEPLOYED copy (e.g. C:\Dev\claude-hooks\
# guard-destructive-azure-sql.py) can also be exercised without editing this
# file.
_HOOK_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "guard-destructive-azure-sql.py")
HOOK = os.environ.get("GUARD_HOOK", _HOOK_DEFAULT)

# A fixed, synthetic repo root for the whole run, independent of whatever
# %USERPROFILE%\repos happens to contain on the machine running the suite.
# Every "in-repo" path below lives under this root; every "off-repo" path
# lives outside it.
TEST_REPO_ROOT = r"C:\repos"

# Every case below drives the real hook, and the hook now APPENDS to an audit log
# on deny/override. Point it at a throwaway file for the whole run: a test suite
# that writes to the real audit trail would make the trail useless (you could
# never tell a real 3am `az group delete` from someone running the tests).
AUDIT_LOG = os.path.join(tempfile.mkdtemp(prefix="guard-audit-test-"),
                         "guard-audit.jsonl")


def audit_records():
    """Every record written to the throwaway log so far, oldest first."""
    if not os.path.exists(AUDIT_LOG):
        return []
    with open(AUDIT_LOG, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]

# (label, command, hard_block, expected) expected in {"deny","ask","silent"}
CASES = [
    # --- destructive Azure / ADO ---
    ("az group delete",          "az group delete -n rg --yes",                 1, "deny"),
    ("az ... --help still hits", "az group delete --help",                      1, "deny"),
    ("ADO repo delete",          "az repos delete --id 123 --yes",              1, "deny"),
    ("ADO pipeline delete",      "az pipelines delete --id 7 --yes",            1, "deny"),
    ("ADO project delete",       "az devops project delete --id p",             1, "deny"),
    ("az keyvault purge",        "az keyvault purge -n kv-foo",                 1, "deny"),
    ("az account clear",         "az account clear",                            1, "deny"),
    # az verbs count ONLY in the command chain (the words between `az` and the
    # first flag), never inside an argument VALUE. Whole-command scanning used
    # to hard-block an ADDITIVE `az repos pr create` twice: once on "DELETE" in
    # a --description, once on "remove" in a --title. Same prose false-positive
    # class the SQL branch fixes below.
    ("PR create, remove in title",
     'az repos pr create --title "fix: remove the re-dating cutover" --org https://x', 1, "silent"),
    ("PR create, DELETE in body",
     'az repos pr create --description "governs an earlier DELETE of rows" --org https://x', 1, "silent"),
    ("prose before the az call",
     '$d = "legacy DELETEs the row"; az repos pr create --description $d',          1, "silent"),
    ("PR complete is additive",   "az repos pr update --id 105 --status completed", 1, "silent"),
    # ...but a real destructive az call stays caught even when fully QUOTED
    # inside another shell -- because the quoted span is being handed to an
    # INTERPRETER, which is what makes it code rather than prose.
    ("quoted az delete in pwsh -c",
     'pwsh -c "az group delete -n rg --yes"',                                      1, "deny"),
    ("quoted az delete in bash -c",
     'bash -c "az group delete -n rg --yes"',                                      1, "deny"),
    ("quoted az delete in cmd /c",
     'cmd /c "az group delete -n rg --yes"',                                       1, "deny"),
    ("az delete after a flag-ish token",
     "az group delete --name rg --no-wait",                                        1, "deny"),
    # The OTHER half of the same seam. An earlier version of the chain scan ran
    # on the raw command so that a quoted invocation was caught, which also
    # meant any PROSE naming an az delete hard-blocked. Real cases: a commit
    # message documenting cleanup work, a note recording the finding (so the bug
    # hid its own evidence), and a READ-ONLY grep whose search pattern contained
    # the words. The discriminator is now whether an interpreter
    # (`pwsh/powershell/bash/sh/cmd` + `-c|-command|/c`) is present, not whether
    # quotes are present. No coverage is lost: the four deny cases directly
    # above are the invocation shapes, and they stay red.
    ("prose: commit msg names an az delete",
     'git commit -m "guard now catches a quoted az group delete invocation"',       1, "silent"),
    ("prose: commit msg names az keyvault purge",
     'git commit -m "document why az keyvault purge is tier 2"',                    1, "silent"),
    ("prose: ledger entry names an az delete",
     'Add-Content -Path C:\\repos\\sample-project\\notes\\OPEN-ITEMS.md -Value "az group delete was blocked in prose"',
                                                                                    1, "silent"),
    ("prose: read-only grep for the words",
     'grep -rn "az group delete" C:\\repos\\sample-project\\shared-tooling',        1, "silent"),
    ("prose: echo naming an az delete",
     'echo "az group delete is what the guard blocks"',                             1, "silent"),
    # A real delete sharing a command line with prose must STILL be caught -- the
    # invocation is outside quotes even though the message is not.
    ("prose beside a real az delete",
     'git commit -m "notes on az group delete"; az group delete -n rg --yes',       1, "deny"),
    # A residual case: prose that itself QUOTES an interpreter invocation. The
    # wrapper now counts only OUTSIDE quotes -- a real `pwsh -c` is never inside
    # its own payload, while a commit message documenting guard work carries it
    # inside the quoted span. This was the self-concealing shape: recording the
    # guard's own repro tripped the guard.
    ("prose quoting a full pwsh -c az delete",
     'git commit -m \'guard: pwsh -c "az group delete -n rg --yes" now blocks\'',   1, "silent"),
    ("ledger entry quoting a full wrapper repro",
     'Add-Content -Path C:\\repos\\sample-project\\notes\\OPEN-ITEMS-detail.md -Value \'repro was pwsh -c "az group delete -n rg"\'',
                                                                                    1, "silent"),
    ("prose quoting a cmd /c az delete",
     'git commit -m \'the cmd /c "az group delete -n rg" hole is closed\'',         1, "silent"),
    # ...and a real wrapper beside quoted prose must STILL deny: the live wrapper
    # sits outside quotes even when the message also names one.
    ("real wrapper beside prose quoting one",
     'git commit -m \'about pwsh -c "az keyvault purge"\' ; pwsh -c "az group delete -n rg --yes"',
                                                                                    1, "deny"),
    # tier-1 seam, same residual: prose quoting a wrapped infra write stays silent,
    # the real wrapped write case below ("real az infra write in pwsh -c
    # asks") keeps asking.
    ("prose quoting a wrapped az infra write",
     'git commit -m \'now catches pwsh -c "az keyvault secret set" too\'',          1, "silent"),
    # The tier-1 az seam has the same defect and the same fix -- one defect can
    # appear at several seams, so closing one and stopping leaves the class
    # alive. `_AZ_INFRA_RESOURCE` is prefixed `(^|\s)az\s+` and a space inside
    # a quoted string is still a space, so this prose used to ask.
    ("prose: commit msg names an az infra write",
     'git commit -m "notes on az keyvault secret set rotation"',                    1, "silent"),
    ("prose: commit msg names az storage account create",
     'git commit -m "why az storage account create needs review"',                  1, "silent"),
    # ...and the real invocations at tier 1 still ask.
    ("real az keyvault secret set asks",
     'az keyvault secret set --vault-name kv --name s --value x',                   1, "ask"),
    ("real az infra write in pwsh -c asks",
     'pwsh -c "az keyvault secret set --vault-name kv --name s --value x"',         1, "ask"),
    # ...an audited-and-ruled extension: the audited silent mutators now ask...
    ("az vm run-command invoke asks",
     'az vm run-command invoke -g rg -n vm --command-id RunPowerShellScript',       1, "ask"),
    ("az webapp slot swap asks",
     'az webapp deployment slot swap -g rg -n app --slot staging',                 1, "ask"),
    ("az resource move asks",
     'az resource move --ids /subscriptions/x --destination-group rg2',            1, "ask"),
    ("az aks upgrade asks",
     'az aks upgrade -g rg -n aks --kubernetes-version 1.30.0 --yes',              1, "ask"),
    # ...and reads on the same resources stay silent.
    ("az vm show silent",        'az vm show -g rg -n vm',                          1, "silent"),
    ("az resource list silent",  'az resource list -g rg -o table',                 1, "silent"),
    # --- SQL, incl. inside a quoted sqlcmd string, both casings ---
    ("DROP upper in sqlcmd",     'sqlcmd -Q "DROP TABLE dbo.foo"',              1, "deny"),
    ("drop lower in sqlcmd",     'sqlcmd -Q "drop table dbo.foo"',              1, "deny"),
    ("TRUNCATE",                 'sqlcmd -Q "TRUNCATE TABLE dbo.foo"',          1, "deny"),
    ("DELETE FROM",              'sqlcmd -Q "delete from dbo.foo"',             1, "deny"),
    ("ALTER..DROP COLUMN",       'sqlcmd -Q "ALTER TABLE t DROP COLUMN c"',     1, "deny"),
    # --- session-scoped throwaways are exempt ---
    # A #temp table dies with the connection, a @table variable with the batch --
    # blocking their cleanup taught operators to route around the guard. Every
    # non-temp or unparseable target still blocks; the mixed-list and lookalike
    # controls prove the exemption cannot leak onto a persistent object.
    ("temp # DROP is silent",
     'sqlcmd -S x -E -Q "IF OBJECT_ID(\'tempdb..#cmp\') IS NOT NULL DROP TABLE #cmp;"', 1, "silent"),
    ("tempdb..# DROP is silent",  'sqlcmd -Q "DROP TABLE tempdb..#stage;"',      1, "silent"),
    ("global ## DROP is silent",  'sqlcmd -Q "DROP TABLE ##shared;"',            1, "silent"),
    ("DROP IF EXISTS temp",       'sqlcmd -Q "DROP TABLE IF EXISTS #tmp;"',      1, "silent"),
    ("temp DROP list, all temp",  'sqlcmd -Q "DROP TABLE #a, ##b, tempdb..#c;"', 1, "silent"),
    ("temp TRUNCATE is silent",   'sqlcmd -Q "TRUNCATE TABLE #stage;"',          1, "silent"),
    ("table-variable DELETE",
     'sqlcmd -Q "DECLARE @t TABLE(x int); DELETE FROM @t;"',                     1, "silent"),
    ("DELETE FROM #temp",         'sqlcmd -Q "DELETE FROM #work;"',              1, "silent"),
    # ...controls: the exemption must fail toward blocking.
    ("mixed DROP temp+real",      'sqlcmd -Q "DROP TABLE #tmp, dbo.Real;"',      1, "deny"),
    ("hash in NAME, not prefix",  'sqlcmd -Q "DROP TABLE dbo.[a#b];"',           1, "deny"),
    ("temp-LIKE schema table",    'sqlcmd -Q "DROP TABLE tempdb.dbo.persisted;"',1, "deny"),
    ("DROP DATABASE never temp",  'sqlcmd -Q "DROP DATABASE tempwork;"',         1, "deny"),
    ("bare drop table, no target",'sqlcmd -Q "drop table"',                      1, "deny"),
    ("DELETE FROM real after temp DROP",
     'sqlcmd -Q "DROP TABLE #t; DELETE FROM dbo.Orders;"',                       1, "deny"),
    # An APOSTROPHE in a comment before the hatch token (here "reviewer's") opens
    # a quote span that swallows #GUARD-OK when any later quote char closes it,
    # so the hatch is not seen. This fails toward BLOCKING (the safe direction)
    # and is pinned here as intended: the fix is to write hatch comments without
    # apostrophes, not to weaken invoked-vs-mentioned.
    ("apostrophe masks the hatch, fails safe",
     "az repos delete --id 1 --yes   # reviewer's ok #GUARD-OK\n"
     "$left = az repos list --query \"[?name=='y']\" -o tsv",                    1, "deny"),
    # --- git history/work destruction (a plain push must stay usable) ---
    ("git force-push",           "git push --force origin main",                1, "deny"),
    ("git push -f",              "git push -f",                                 1, "deny"),
    # `Push-Location` satisfies a bare `push\b` and the PowerShell format
    # operator supplies the ` -f`, which used to hard-block a read-only status
    # loop.
    ("Push-Location + -f fmt op",
     'foreach ($r in 1..3) { Push-Location "C:\\repos\\sample-project\\x"; "{0,-16}" -f $r; Pop-Location }\n'
     'git -C "C:\\repos\\sample-project\\x" status --porcelain',                 1, "silent"),
    # ...and the fix must not cost the `git -C <repo>` form, which needs no `cd`.
    ("git -C force-push",        "git -C C:\\repos\\sample-project\\x push --force",  1, "deny"),
    ("git reset --hard",         "git reset --hard HEAD~3",                     1, "deny"),
    ("git clean -fd",            "git clean -fd",                               1, "deny"),
    ("plain git push allowed",   "git push origin main",                        1, "silent"),
    # The force flag must share push's SEGMENT -- it is an argument to the push
    # itself, so it cannot cross `;`/`|`/`&` or a newline. An earlier unscoped
    # `.*` paired a format operator's ` -f` in the NEXT segment with the push and
    # denied an ordinary push-then-log compound as a force-push.
    ("push then -f fmt op next segment",
     'git push origin main; Write-Host ("pushed at {0}" -f (Get-Date))',         1, "silent"),
    ("force-with-lease same segment", "git push origin main --force-with-lease", 1, "deny"),
    # --- filesystem ---
    ("rm outside repo root",     "rm -r /c/windows/temp/x",                     1, "deny"),
    ("Remove-Item off-repo",     "Remove-Item C:\\Windows\\Temp\\x.txt",        1, "deny"),
    ("Remove-Item in repo root", "Remove-Item C:\\repos\\sample-project\\scratch.txt", 1, "silent"),
    # The pipe splits this into two segments; "Remove-Item" alone (no path in
    # ITS segment) is an unverifiable target -> tier 1 ask, not tier 2 deny --
    # same as every other unverifiable-target case below.
    ("piped Remove-Item",        "Get-ChildItem C:\\Temp | Remove-Item",        1, "ask"),
    ("find -delete",             "find . -name '*.tmp' -delete",                1, "deny"),
    # --- PSDrive targets (regression): session-scoped providers are not file
    #     deletes and must pass; persistent ones must still be gated.
    ("Env:\\ var delete",        "Remove-Item Env:\\GUARD_HARD_BLOCK",          1, "silent"),
    ("Env: no backslash",        "Remove-Item Env:FOO",                         1, "silent"),
    ("Env: via -Path",           "Remove-Item -Path Env:\\FOO",                 1, "silent"),
    ("Variable:\\ delete",       "Remove-Item Variable:\\scratch",              1, "silent"),
    ("Function:\\ delete",       "Remove-Item Function:\\Get-Thing",            1, "silent"),
    ("Alias:\\ delete",          "Remove-Item Alias:\\ll",                      1, "silent"),
    ("registry delete gated",    "Remove-Item HKLM:\\Software\\Foo -Recurse",   1, "deny"),
    ("HKCU delete gated",        "Remove-Item HKCU:\\Environment\\Foo",         1, "deny"),
    ("Cert: delete gated",       "Remove-Item Cert:\\LocalMachine\\My\\AB12",   1, "deny"),
    # the exemption must not shield a real path sitting beside it
    ("Env: + off-repo path",
     "Remove-Item Env:\\FOO, C:\\Windows\\x.txt",                               1, "deny"),
    ("Env: + in-repo path",
     "Remove-Item Env:\\FOO, C:\\repos\\sample-project\\y.txt",                 1, "silent"),
    # $env:VAR is variable EXPANSION, not a PSDrive target -- this deletes a real
    # file, but the guard cannot resolve the variable to a literal path, so it is
    # an unverifiable target -> tier 1 ask, same as a relative path.
    ("$env:TEMP expansion -> ask", "Remove-Item $env:TEMP\\x.txt",              1, "ask"),
    # --- prose that merely MENTIONS a delete must not be blocked (regression:
    #     this hook's own fix commit was blocked by its own message). Same rule
    #     as the SQL cases: the VERB must appear outside quotes to count as an
    #     invocation.
    ("commit msg names Remove-Item",
     'git commit -m "guard: Remove-Item C:\\Windows\\x is now blocked"',        1, "silent"),
    ("commit msg names rm -rf",
     'git commit -m "note: rm -rf outside the repo root is denied"',            1, "silent"),
    ("echo prose about del",
     'echo "never run del C:\\temp\\x on this host" >> notes.md',               1, "silent"),
    ("grep for a delete verb",   "grep -rn 'Remove-Item' C:/repos/sample-project", 1, "silent"),
    # ...but an unquoted verb with a quoted TARGET is still a real invocation
    ("quoted target still caught",
     'Remove-Item "C:\\Program Files\\junk.txt"',                               1, "deny"),
    ("quoted in-repo target ok",
     'Remove-Item "C:\\repos\\sample-project\\junk.txt"',                       1, "silent"),
    # --- the rooted-path check is scoped to the DELETE's own segment. It used
    #     to require EVERY rooted path in the whole command to be under the
    #     repo root, so an unrelated path merely being READ elsewhere forced a
    #     block -- even when the delete target was a session-scoped Env: drive.
    #     It blocked routine cleanup scripts and this suite's own coverage test.
    ("in-repo delete + unrelated C: read",
     "Get-Content C:\\Users\\other\\note.txt; Remove-Item C:\\repos\\sample-project\\s.txt", 1, "silent"),
    ("Env: delete + unrelated C: read",
     "Get-Content C:\\Users\\other\\note.txt; Remove-Item Env:\\FOO",          1, "silent"),
    ("in-repo delete + quoted off-repo prose",
     'Write-Output "check C:\\Windows first"; Remove-Item C:\\repos\\sample-project\\a.txt', 1, "silent"),
    # ...without letting a genuinely off-repo delete hide inside a compound command
    ("off-repo delete in compound",
     "Get-Content C:\\repos\\sample-project\\x.txt; Remove-Item C:\\Windows\\y.txt", 1, "deny"),
    ("two deletes, one off-repo",
     "Remove-Item C:\\repos\\sample-project\\a.txt; Remove-Item C:\\Windows\\b.txt", 1, "deny"),
    # Case: a relative delete target after a directory change is asked about (tier 1).
    ("cd off-repo then relative rm",  "cd C:\\Windows && rm -rf .",               1, "ask"),
    ("newline-separated off-repo delete",
     "Get-Date\nRemove-Item C:\\Windows\\y.txt",                                  1, "deny"),
    # --- POSIX drive forms. _ROOTED_PATH knew the Windows form,
    #     //<drive>/repos/... and UNC \\... but an earlier version was MISSING
    #     Git Bash's single-slash /<drive>/repos/... and /cygdrive/<drive>/...,
    #     so every Bash-tool delete inside the repo root matched no rooted path
    #     and fell into the fail-safe "unverifiable target" branch and
    #     hard-blocked. It failed CLOSED (annoyance, not hole) but blocked
    #     routine housekeeping repeatedly. The token-boundary lookbehind is what
    #     keeps the new /<letter>/ form from matching a URL path
    #     (`https://host/x/y`) or a relative `./a/b`.
    ("POSIX in-repo rm",         "rm -f /c/repos/sample-project/scratch.txt",   1, "silent"),
    ("POSIX in-repo rm -rf dir", "rm -rf /c/repos/sample-project/tmpdir",       1, "silent"),
    ("POSIX in-repo, quoted",    'rm -f "/c/repos/sample-project/junk file.txt"', 1, "silent"),
    ("double-slash in-repo rm",  "rm -f //c/repos/sample-project/s.txt",        1, "silent"),
    ("cygdrive in-repo rm",      "rm -f /cygdrive/c/repos/sample-project/s.txt",1, "silent"),
    ("POSIX off-repo still denied",   "rm -rf /c/windows/temp/x",                1, "deny"),
    ("cygdrive off-repo denied",      "rm -f /cygdrive/c/windows/x.txt",         1, "deny"),
    # THE discriminator for "blocks for the DELIBERATE reason, not by luck": an
    # off-repo POSIX path sitting in the SAME delete segment as an in-repo one.
    # If the off-repo form were left unrecognised while the in-repo form became
    # recognised, `rooted` would hold only the in-repo path, all() would pass,
    # and this would go SILENT while really deleting the off-repo file -- a
    # fail-OPEN introduced by a partial fix. The single-path case alone cannot
    # catch that: it denies either way.
    ("POSIX in-repo + off-repo in one delete",
     "rm -f /c/repos/a.txt /c/windows/b.txt",                                   1, "deny"),
    ("cygdrive in-repo + off-repo in one delete",
     "rm -f /cygdrive/c/repos/a.txt /cygdrive/c/windows/b.txt",                 1, "deny"),
    # POSIX forms must not weaken the fail-safe branches either -- same
    # outcome as the Windows-form case above: unverifiable target -> ask.
    ("POSIX cd off-repo then relative rm", "cd /c/windows && rm -rf .",          1, "ask"),
    ("POSIX unrelated read + in-repo delete",
     "cat /c/users/other/note.txt; rm -f /c/repos/sample-project/s.txt",         1, "silent"),
    ("POSIX off-repo delete in compound",
     "cat /c/repos/x.txt; rm -f /c/windows/y.txt",                               1, "deny"),
    # --- prose that merely MENTIONS SQL must not be blocked (regression) ---
    ("commit msg mentions DROP",
     'git commit -m "fix: guard now catches DROP TABLE inside sqlcmd strings"',  1, "silent"),
    ("commit msg lowercase",
     'git commit -m "note: *drop table* missed DROP TABLE (case-sensitive)"',    1, "silent"),
    ("echo prose about DELETE",
     'echo "we must never run DELETE FROM dbo.foo on prod" >> notes.md',         1, "silent"),
    ("grep for the word",       "grep -rn 'TRUNCATE TABLE' C:/repos/sample-project", 1, "silent"),
    # --- but a real SQL client still gets caught ---
    ("Invoke-Sqlcmd DROP",      'Invoke-Sqlcmd -Query "DROP TABLE dbo.foo"',     1, "deny"),
    ("sqlcmd.exe full path",
     '"/c/Program Files/.../sqlcmd.exe" -Q "TRUNCATE TABLE dbo.foo"',            1, "deny"),
    ("az sql db delete",        "az sql db delete -n db -s srv -g rg --yes",     1, "deny"),
    # --- safe work must never be touched ---
    ("safe az",                  "az account show --query name -o tsv",         1, "silent"),
    ("safe sqlcmd SELECT",       'sqlcmd -Q "SELECT TOP 10 * FROM dbo.foo"',    1, "silent"),
    ("safe PowerShell",          "Get-Date -Format o",                          1, "silent"),
    ("safe git",                 "git status -sb",                              1, "silent"),
    ("az list",                  "az group list -o table",                      1, "silent"),
    # --- escape hatch ---
    ("token stands down",        'sqlcmd -Q "DROP TABLE dbo.foo" #GUARD-OK',    1, "silent"),
    ("token lowercase form",     "az group delete -n rg --yes #guard-ok",       1, "silent"),
    ("token mixed case",         "az group delete -n rg --yes #Guard-Ok",       1, "silent"),
    # ...but the token must be INVOKED (outside quotes), not merely MENTIONED.
    # An earlier version failed OPEN here: the check was a substring match on
    # the raw command, so any commit message or doc string naming the token
    # disarmed the guard completely -- and this token gets discussed constantly.
    # Same invoked-vs-mentioned rule as the SQL clients and delete verbs, but
    # this one leaked the dangerous way.
    ("quoted token does NOT disarm",
     'git commit -m "document the #GUARD-OK hatch"; az group delete -n rg --yes',  1, "deny"),
    ("quoted token, real rm still caught",
     'echo "see #guard-ok in the docs"; rm -rf /c/Windows/Temp/x',                 1, "deny"),
    ("quoted token alone stays silent",
     'git commit -m "document the #GUARD-OK hatch"',                              1, "silent"),
    # --- soft mode (no broad allowlist): ask, not deny ---
    ("soft: destructive asks",   "az group delete -n rg --yes",                 0, "ask"),
    ("soft: safe silent",        "az account show",                             0, "silent"),

    # =========================================================================
    # Tier 1 -- consequential but recoverable. ALWAYS "ask" in BOTH modes: run
    # these at hard=1 specifically to prove they do NOT escalate to "deny" the
    # way a tier-2 case would.
    # =========================================================================
    ("SQL UPDATE via sqlcmd",    'sqlcmd -Q "UPDATE dbo.foo SET x=1"',          1, "ask"),
    ("SQL INSERT via sqlcmd",    'sqlcmd -Q "INSERT INTO dbo.foo VALUES (1)"',  1, "ask"),
    ("SQL EXEC via sqlcmd",      'sqlcmd -Q "EXEC dbo.usp_DoThing"',            1, "ask"),
    ("SQL sp_configure",         'sqlcmd -Q "EXEC sp_configure @a"',            1, "ask"),
    ("SQL SELECT still silent",  'sqlcmd -Q "SELECT * FROM dbo.foo"',           1, "silent"),
    ("az vm create",             "az vm create -n vm1 -g rg --image ubuntu",    1, "ask"),
    ("az keyvault secret set",   "az keyvault secret set --vault-name kv -n s --value x", 1, "ask"),
    ("az role assignment create", "az role assignment create --role Owner --assignee x", 1, "ask"),
    ("az network nsg rule create", "az network nsg rule create --nsg-name n --access Allow", 1, "ask"),
    ("az storage account update", "az storage account update -n s -g rg --allow-blob-public-access true", 1, "ask"),
    ("az sql db restore",        "az sql db restore -n db --dest-name db2 -s srv -g rg", 1, "ask"),
    ("az account show silent",   "az account show",                             1, "silent"),
    ("ADO repo create stays silent", "az repos pr create --title x",            1, "silent"),
    ("curl POST",                "curl -X POST https://graph.microsoft.com/v1.0/x", 1, "ask"),
    ("curl GET stays silent",    "curl -s https://graph.microsoft.com/v1.0/x",  1, "silent"),
    ("Invoke-RestMethod POST",   "Invoke-RestMethod -Method POST -Uri https://x", 1, "ask"),
    ("az rest post",             "az rest --method post --url https://graph.microsoft.com/v1.0/x", 1, "ask"),
    ("git checkout -- discard",  "git checkout -- .",                           1, "ask"),
    ("git restore discard",      "git restore --staged foo.py",                 1, "ask"),
    ("git stash drop",           "git stash drop",                              1, "ask"),
    ("git rebase",                "git rebase main",                             1, "ask"),
    ("git commit --amend",       "git commit --amend -m x",                     1, "ask"),
    ("git branch -D now ask",    "git branch -D feature/dead",                  1, "ask"),
    ("npm install",              "npm install lodash",                          1, "ask"),
    ("npm ci stays silent",      "npm ci",                                      1, "silent"),
    ("pip install",              "pip install requests",                        1, "ask"),
    ("SetEnvironmentVariable",   "[Environment]::SetEnvironmentVariable('X','1','User')", 1, "ask"),
    ("icacls grant",             "icacls C:\\Temp /grant Everyone:F /T",        1, "ask"),
    ("chmod -R",                 "chmod -R 777 /some/dir",                      1, "ask"),
    ("Stop-Service",             "Stop-Service MSSQLSERVER -Force",             1, "ask"),
    ("New-LocalUser",            "New-LocalUser -Name foo -Password bar",       1, "ask"),
    ("schtasks create",          "schtasks /create /tn foo /tr bar /sc daily",  1, "ask"),
    ("reg add",                  "reg add HKLM\\Software\\Foo /v Bar /d 1",     1, "ask"),
    ("Set-Content outside repo root", "Set-Content C:\\Windows\\Temp\\x.txt -Value 'y'", 1, "ask"),
    ("Set-Content in repo root stays silent",
     "Set-Content C:\\repos\\sample-project\\x.txt -Value 'y'",                1, "silent"),
    ("sed -i outside repo root",     "sed -i 's/a/b/' /c/windows/temp/x.txt",  1, "ask"),
    ("sed -i in repo root stays silent", "sed -i 's/a/b/' /c/repos/sample-project/x.txt", 1, "silent"),
    ("Set-Content relative stays silent", "Set-Content x.txt -Value 'y'",       1, "silent"),
]


def run(cmd, hard):
    env = dict(os.environ)
    env["GUARD_AUDIT_LOG"] = AUDIT_LOG
    env["GUARD_REPO_ROOT"] = TEST_REPO_ROOT
    if hard:
        env["GUARD_HARD_BLOCK"] = "1"
    else:
        env.pop("GUARD_HARD_BLOCK", None)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    p = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True,
                       text=True, env=env)
    if p.returncode != 0:
        return "ERROR rc=%s %s" % (p.returncode, p.stderr.strip()[:200])
    out = p.stdout.strip()
    if not out:
        return "silent"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "UNPARSEABLE: %s" % out[:120]


fails = 0
for label, cmd, hard, want in CASES:
    got = run(cmd, hard)
    ok = got == want
    if not ok:
        fails += 1
    print("%s  %-26s want=%-6s got=%s" % ("PASS" if ok else "FAIL", label, want, got))


# --- the settings.json self-escalation interlock ---------------------------------
# The Edit/Write route to a live settings file must ASK in BOTH modes; everything
# that is not a live surface must stay silent, or the rule becomes noise.
def run_file(tool, tool_input, hard):
    env = dict(os.environ)
    env["GUARD_AUDIT_LOG"] = AUDIT_LOG
    env["GUARD_REPO_ROOT"] = TEST_REPO_ROOT
    if hard:
        env["GUARD_HARD_BLOCK"] = "1"
    else:
        env.pop("GUARD_HARD_BLOCK", None)
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    p = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True,
                       text=True, env=env)
    if p.returncode != 0:
        return "ERROR rc=%s %s" % (p.returncode, p.stderr.strip()[:200])
    out = p.stdout.strip()
    if not out:
        return "silent"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "UNPARSEABLE: %s" % out[:120]


FILE_CASES = [
    # (label, tool, tool_input, hard, want)
    ("Edit user settings -> ask",
     "Edit", {"file_path": "C:\\claude-config\\settings.json"}, 0, "ask"),
    ("hard mode still ASK not deny",
     "Edit", {"file_path": "C:\\claude-config\\settings.json"}, 1, "ask"),
    ("Write seat-dir settings -> ask",
     "Write", {"file_path": "C:\\claude-config\\someuser\\settings.json"}, 1, "ask"),
    ("repo .claude settings.local",
     "Edit", {"file_path": "C:/repos/sample-project/shared-tooling/.claude/settings.local.json"}, 1, "ask"),
    ("settings.template.json free",
     "Edit", {"file_path": "C:\\repos\\sample-project\\shared-tooling\\onboarding\\settings.template.json"}, 1, "silent"),
    ("ordinary Edit stays silent",
     "Edit", {"file_path": "C:\\repos\\sample-project\\shared-tooling\\docs\\ACCESS.md"}, 1, "silent"),
    ("deep claude-config path free",
     "Write", {"file_path": "C:\\claude-config\\projects\\x\\y\\settings.json"}, 1, "silent"),
    ("keybindings not a surface",
     "Edit", {"file_path": "C:\\claude-config\\keybindings.json"}, 1, "silent"),
]

for label, tool, ti, hard, want in FILE_CASES:
    got = run_file(tool, ti, hard)
    ok = got == want
    if not ok:
        fails += 1
    print("%s  %-26s want=%-6s got=%s" % ("PASS" if ok else "FAIL", label, want, got))


# --- Pattern-level contract for the path regexes -------------------------------
# The end-to-end cases above cannot distinguish "blocked because it is provably
# outside the repo root" from "blocked because no path was provable at all" --
# both return the same reason string. These assert the classification directly,
# which is also the cheapest place to pin that the /<letter>/ form does NOT
# invent phantom paths out of URLs or relative paths (a phantom UNDER repos
# would grant silence; a phantom off-repo would cause a spurious block).
os.environ["GUARD_REPO_ROOT"] = TEST_REPO_ROOT
_spec = importlib.util.spec_from_file_location("guard", HOOK)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

PATTERN_CASES = [
    # (text, expected rooted-path matches, expected under-repos verdicts)
    ("rm -f /c/repos/sample-project/s.txt", ["/c/repos/sample-project/s.txt"], [True]),
    ("rm -f /cygdrive/c/repos/a.txt",      ["/cygdrive/c/repos/a.txt"],      [True]),
    ("rm -f //c/repos/a.txt",              ["//c/repos/a.txt"],              [True]),
    ("rm -f c:/repos/a.txt",               ["c:/repos/a.txt"],               [True]),
    ("rm -rf /c/windows/temp/x",           ["/c/windows/temp/x"],            [False]),
    ("rm -f /cygdrive/c/windows/x",        ["/cygdrive/c/windows/x"],        [False]),
    # the repos ROOT itself is not "under" repos -- deleting it must stay gated,
    # matching the existing c:\repos\ rule which also requires a trailing separator
    ("rm -rf /c/repos",                    ["/c/repos"],                     [False]),
    # phantom guards: neither a URL path nor a relative path is a rooted path
    ("curl -s https://example.com/x/y",    [],                               []),
    ("rm -f ./x/y",                        [],                               []),
    ("rm -f a/b/c",                        [],                               []),
    # /tmp is not a drive-letter form; it stays unverifiable (and thus gated)
    ("rm -rf /tmp/foo",                    [],                               []),
]

for text, want_paths, want_under in PATTERN_CASES:
    got_paths = guard._ROOTED_PATH.findall(text)
    got_under = [bool(guard._UNDER_REPOS.match(p)) for p in got_paths]
    ok = got_paths == want_paths and got_under == want_under
    if not ok:
        fails += 1
    print("%s  %-26s paths=%s under=%s" % ("PASS" if ok else "FAIL",
                                           text[:26], got_paths, got_under))

# --- Audit-log contract ---------------------------------------------------------
# The log exists because a `#GUARD-OK` override and a tier-2 `deny` are otherwise
# invisible after the fact. Two things therefore have to hold, and only one of
# them is obvious: the events that matter ARE written, and the events that don't
# are NOT. The second half is what keeps the log worth reading -- a trail that
# also records every routine "ask", or every command that merely carries the
# token, is one nobody scans, which is the same failure as no trail at all.
#
# (label, command, hard_block, expected decision, expected new records)
# Each expected record is (event, tier) or None for "nothing logged".
AUDIT_CASES = [
    ("deny is logged",        "az group delete -n rg --yes",            1, "deny",   ("deny", 2)),
    ("soft-mode ask is not",  "az group delete -n rg --yes",            0, "ask",    None),
    ("tier-1 ask is not",     "npm install left-pad",                   1, "ask",    None),
    ("tier-2 override logged","az group delete -n rg --yes #GUARD-OK",  1, "silent", ("override", 2)),
    ("tier-1 override logged","npm install left-pad #GUARD-OK",         1, "silent", ("override", 1)),
    # The token on a command the guard would have passed anyway is a non-event.
    ("no-op token not logged","git status #GUARD-OK",                   1, "silent", None),
    # The token INSIDE the quoted SQL is blanked by unquoted(), so it does not
    # stand the guard down -- and the resulting block must still be logged as a
    # deny, not swallowed as an override.
    ("quoted token != hatch", 'sqlcmd -S x -Q "DROP TABLE t -- #GUARD-OK"', 1, "deny", ("deny", 2)),
]

for label, cmd, hard, want, want_rec in AUDIT_CASES:
    before = len(audit_records())
    got = run(cmd, hard)
    new = audit_records()[before:]
    if want_rec is None:
        ok = got == want and not new
        detail = "logged=%d" % len(new)
    else:
        ok = (got == want and len(new) == 1
              and new[0].get("event") == want_rec[0]
              and new[0].get("tier") == want_rec[1]
              and new[0].get("cmd") == cmd
              and new[0].get("rule"))
        detail = "rec=%s" % ([(r.get("event"), r.get("tier"), r.get("rule")) for r in new],)
    if not ok:
        fails += 1
    print("%s  %-26s want=%-6s got=%-6s %s" % ("PASS" if ok else "FAIL",
                                               label, want, got, detail))

total = len(CASES) + len(FILE_CASES) + len(PATTERN_CASES) + len(AUDIT_CASES)
print("\n%d/%d passed" % (total - fails, total))
sys.exit(1 if fails else 0)
