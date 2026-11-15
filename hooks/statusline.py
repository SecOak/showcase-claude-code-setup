#!/usr/bin/env python
"""Statusline (shared): user | model | folder | context used.

Answers "how full is the context, should I start a new session?" at a glance,
so the question never needs asking.

Reads the statusline JSON from stdin. Context fields vary between Claude Code
builds, so this searches defensively for anything context-window-shaped and
degrades gracefully to omitting the segment.
"""
import json
import os
import sys


def find_context(node):
    """Walk the JSON for a dict that looks like {used/current tokens, max/size}."""
    if isinstance(node, dict):
        keys = {k.lower(): k for k in node.keys()}
        used_key = next((keys[k] for k in keys if k in
                         ("used_tokens", "input_tokens", "used", "current_tokens", "total_input_tokens")), None)
        max_key = next((keys[k] for k in keys if k in
                        ("max_tokens", "context_window", "size", "max", "context_limit", "total_tokens_limit")), None)
        if used_key and max_key:
            try:
                used, mx = float(node[used_key]), float(node[max_key])
                if mx > 0 and used >= 0:
                    return used, mx
            except (TypeError, ValueError):
                pass
        for k, v in node.items():
            if "context" in str(k).lower() or isinstance(v, dict):
                got = find_context(v)
                if got:
                    return got
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    user = os.environ.get("USERNAME", "?")
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id", "?")
    cwd = os.path.basename((data.get("workspace") or {}).get("current_dir", "") or "") or "?"
    parts = [user, str(model), cwd]
    ctx = find_context(data)
    if ctx:
        pct = min(100, round(100 * ctx[0] / ctx[1]))
        flag = " !! consider /compact or a new session" if pct >= 80 else ""
        parts.append(f"ctx {pct}%{flag}")
    elif data.get("exceeds_200k_tokens"):
        parts.append("ctx LARGE -- consider /compact or a new session")
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
