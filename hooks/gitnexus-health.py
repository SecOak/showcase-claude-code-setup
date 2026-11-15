#!/usr/bin/env python3
"""SessionStart hook -- make a broken/absent GitNexus LOUD instead of silent.

What it checks, cheapest first:
  1. cwd is a git repo (else silent -- never nag outside a repo)
  2. gitnexus is registered for this project (user scope or project-local)
  3. the repo has a .gitnexus/ index
  4. the indexed commit matches HEAD
  5. the server actually completes an MCP initialize handshake (spawn probe,
     result cached 24h so this costs ~0s on most session starts)

Output is a banner the model is told to SURFACE TO THE USER IMMEDIATELY. A
hook whose output only reaches the model's context does not, by itself,
guarantee the user sees it -- the banner carries that instruction explicitly.

Always exits 0. A health check must never block a session.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# A hook process can inherit a non-UTF-8 stdout codepage; one non-ASCII
# character in anything printed below would raise UnicodeEncodeError and be
# swallowed by the except-and-exit-0 pattern every hook here uses. Pin it --
# do not rely on PYTHONIOENCODING, which is not guaranteed to reach the hook
# process depending on how it is launched.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Deployed layout: this script and the gitnexus-mcp.cmd launcher it probes
# both live in CLAUDE_HOOKS_DIR (default C:\Dev\claude-hooks). CLAUDE_JSON is
# Claude Code's own config file, which normally lives in the user's home
# directory (or wherever CLAUDE_CONFIG_DIR points, if that env var is set).
CLAUDE_HOOKS_DIR = Path(os.environ.get("CLAUDE_HOOKS_DIR", os.path.expandvars(r"C:\Dev\claude-hooks")))
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expandvars(r"%USERPROFILE%")))
CLAUDE_JSON = CONFIG_DIR / ".claude.json"
WRAPPER = CLAUDE_HOOKS_DIR / "gitnexus-mcp.cmd"
LOG_DIR = Path(os.path.expandvars(r"%TEMP%\mcp-logs"))
LOG_GLOB = f"gitnexus-mcp-{os.environ.get('USERNAME', '*')}-*.log"
# The wrapper writes ONE LOG PER LAUNCH rather than appending to a single
# fixed path -- a fixed path holds a Windows share-lock for the life of the
# server and makes gitnexus single-instance, which would make this hook's own
# probe (a second instance) fail whenever gitnexus was actually working. See
# the wrapper's own comments for the full story.
LOG_KEEP = 12          # newest N launch logs; older ones are deleted
LOG_MAX_AGE = 7 * 86400
PROBE_STAMP = LOG_DIR / ".gitnexus-probe-ok"
PROBE_TTL = 24 * 3600
PROBE_TIMEOUT = 25

# Repos that are documentation/data only -- a code knowledge graph buys
# nothing there, so absence of an index is correct, not a finding. Keep this
# honest: add a repo only after confirming it has no code worth graphing.
DOC_ONLY = set()


def emit(context):
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
        sys.stdout,
    )
    sys.exit(0)


def quiet():
    sys.exit(0)


def git(cwd, *args):
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=10,
            # encoding is NOT optional. text=True alone decodes the child's
            # output with the locale codec, and one undefined byte raises
            # UnicodeDecodeError inside subprocess's reader THREAD -- which
            # this module's bare excepts then swallow into exit 0.
            encoding="utf-8", errors="replace",
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def newest_log():
    """Path of the most recent launch log, or None."""
    try:
        logs = sorted(LOG_DIR.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
        return logs[0] if logs else None
    except Exception:
        return None


def prune_logs():
    """Delete old launch logs. NEVER rename or truncate one.

    A previous version of this pattern renamed a fixed-name log to rotate it.
    On Windows that renames a file a live server still holds open -- it
    raises, and one of this module's bare excepts ate it. Deleting only files
    that are old AND not the newest keeps us off any handle a running server
    owns; a delete that loses the race raises PermissionError and is skipped,
    which is correct.
    """
    try:
        logs = sorted(LOG_DIR.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime, reverse=True)
        now = time.time()
        for i, p in enumerate(logs):
            if i < LOG_KEEP and (now - p.stat().st_mtime) < LOG_MAX_AGE:
                continue
            try:
                p.unlink()
            except OSError:
                pass  # still held by a live server -- leave it, catch it next time
    except Exception:
        pass
    # The wrapper claims each log name with an atomic `md` and removes the
    # claim on exit. A killed wrapper leaks one; left forever they would
    # slowly force the claim loop to retry more. Anything older than a day
    # cannot belong to a live server.
    try:
        for d in LOG_DIR.glob(".claim-*"):
            if d.is_dir() and (time.time() - d.stat().st_mtime) > 86400:
                try:
                    d.rmdir()
                except OSError:
                    pass
    except Exception:
        pass


def is_registered(cwd):
    """True if this project would get a gitnexus MCP server, at any scope."""
    try:
        cfg = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None  # can't tell -- don't cry wolf
    if "gitnexus" in (cfg.get("mcpServers") or {}):
        return True
    # project-local scope. Keys use FORWARD slashes; a backslash lookup
    # returns null and looks exactly like "not configured."
    projects = cfg.get("projects") or {}
    for key in (str(cwd).replace("\\", "/"), str(cwd)):
        entry = projects.get(key)
        if entry and "gitnexus" in (entry.get("mcpServers") or {}):
            return True
    return False


def index_status(cwd):
    """(indexed_commit, current_commit) per `gitnexus status`, or (None, None).

    Deliberately NOT read from .gitnexus/meta.json. meta.json describes only
    the flat/primary-branch slot; per-branch indexes live in
    .gitnexus/branches/. On any non-primary branch a meta.json comparison
    reports STALE for a repo that was just indexed -- which is exactly the
    false positive this hook exists to avoid producing. `gitnexus status` is
    branch-aware; it is the only honest source.
    """
    try:
        r = subprocess.run(["gitnexus", "status"], cwd=str(cwd), capture_output=True,
                           text=True, timeout=30, shell=True,
                           encoding="utf-8", errors="replace")  # see git() above
    except Exception:
        return None, None
    indexed = current = None
    for line in (r.stdout or "").splitlines():
        if "Indexed commit:" in line:
            indexed = line.split("Indexed commit:", 1)[1].strip()
        elif "Current commit:" in line:
            current = line.split("Current commit:", 1)[1].strip()
    return indexed, current


def probe():
    """Spawn the server and require a JSON-RPC initialize reply. Cached 24h.
    Returns (True, detail) on reply, (False, detail) on a fast failure,
    (None, detail) on timeout -- inconclusive, see below."""
    try:
        if PROBE_STAMP.exists() and time.time() - PROBE_STAMP.stat().st_mtime < PROBE_TTL:
            return True, "cached"
    except Exception:
        pass
    fallback = os.path.expandvars(r"%USERPROFILE%\npm-global\gitnexus.cmd")
    cmd = str(WRAPPER) if WRAPPER.exists() else fallback
    args = [cmd] if WRAPPER.exists() else [cmd, "mcp"]
    frame = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "healthcheck", "version": "1"}},
    })
    t0 = time.time()
    try:
        r = subprocess.run(args, input=frame + "\n", capture_output=True,
                           text=True, timeout=PROBE_TIMEOUT, shell=False,
                           encoding="utf-8", errors="replace")  # see git() above
    except subprocess.TimeoutExpired:
        # A slow reply is NOT a break. A cold launch of the server measures
        # several seconds to over ten alone, longer inside a real SessionStart
        # where many MCP servers cold-start alongside this probe. So a
        # timeout is inconclusive: report it as such, write no stamp
        # (re-probe next session), and never call it HANDSHAKE FAILED.
        return None, (f"PROBE INCONCLUSIVE -- no initialize reply within {PROBE_TIMEOUT}s. "
                      f"A cold launch alone can take well over ten seconds; this is likely "
                      f"startup contention, not a break. Re-probes next session.")
    except Exception as exc:
        return False, f"spawn failed: {exc}"
    dt = time.time() - t0
    if '"serverInfo"' not in (r.stdout or ""):
        tail = (r.stderr or "").strip().splitlines()[-3:]
        return False, f"no serverInfo in reply after {dt:.1f}s; stderr: {' | '.join(tail) or '(empty)'}"
    try:
        PROBE_STAMP.parent.mkdir(parents=True, exist_ok=True)
        PROBE_STAMP.write_text(f"ok {dt:.2f}s")
    except Exception:
        pass
    return True, f"{dt:.1f}s"


def main():
    prune_logs()
    cwd = Path.cwd()
    if not git(cwd, "rev-parse", "--git-dir"):
        quiet()  # not a git repo -- nothing to say

    repo = cwd.name
    problems = []

    reg = is_registered(cwd)
    if reg is False:
        problems.append(
            "NOT REGISTERED -- there is no gitnexus MCP server configured for this "
            "project, so no mcp__gitnexus__* tool exists in this session. "
            f"Fix: `claude mcp add gitnexus --scope user -- {WRAPPER}` "
            "(user scope covers every repo), then restart the session."
        )

    if repo not in DOC_ONLY:
        if not (cwd / ".gitnexus").is_dir():
            problems.append(
                f"NO INDEX -- {repo} has never been analyzed, so impact()/detect_changes() "
                f"have nothing to answer from. Fix: `gitnexus analyze --skip-agents-md` in the repo root."
            )
        else:
            indexed, current = index_status(cwd)
            if indexed and current and indexed != current:
                problems.append(
                    f"STALE INDEX -- indexed at {indexed}, HEAD is {current}. Symbols added since "
                    f"are invisible to impact(). Fix: `gitnexus analyze --skip-agents-md`."
                )

    if reg is not False:  # pointless to probe a server that isn't wired up
        ok, detail = probe()
        if ok is None:          # timed out: inconclusive, one line, no diagnosis
            problems.append(detail)
        elif not ok:
            # Name the LAUNCH, not the binary. Blaming whichever component
            # you happened to be probing is a diagnosis, and a launcher-level
            # fault (e.g. a log-file lock preventing a second instance from
            # starting) can look identical to a broken binary. Compare
            # against the raw binary before concluding which one is at fault.
            where = newest_log()
            fallback = os.path.expandvars(r"%USERPROFILE%\npm-global\gitnexus.cmd")
            problems.append(
                f"HANDSHAKE FAILED -- the gitnexus LAUNCH did not answer an MCP initialize "
                f"frame ({detail}). This says the launch failed, NOT that the binary is "
                f"broken: check the wrapper and the log directory before the server. "
                f"Compare against the raw binary -- "
                f"`{fallback} mcp` -- and if THAT answers, the fault is in "
                f"{WRAPPER}. "
                f"Newest launch log: {where if where else LOG_DIR}"
            )

    if not problems:
        quiet()

    body = "\n".join(f"  {i}. {p}" for i, p in enumerate(problems, 1))
    # NB: keep the rule in its own name. Inlining `"=" * 72` between adjacent
    # string literals multiplies the WRONG operand -- implicit concatenation
    # binds tighter than `*`, so the banner text repeats 72 times.
    rule = "=" * 72
    emit(
        rule + "\n"
        "GITNEXUS HEALTH CHECK FAILED -- SURFACE THIS TO THE USER IN YOUR FIRST MESSAGE.\n"
        + rule + "\n"
        f"Repo: {repo}\n{body}\n\n"
        "GitNexus must be installed and running for git work in this repo, and if it is "
        "not working you must stop and tell the user. Do not silently fall back to grep "
        "for blast-radius questions -- say plainly that impact()/detect_changes() are "
        "unavailable, and let the user decide whether to fix it or proceed without them.\n"
        "Confirm the live state yourself before reporting: ToolSearch for mcp__gitnexus__* "
        "(it waits for still-connecting servers, so a miss is real evidence, not a race).\n"
        + rule
    )


if __name__ == "__main__":
    main()
