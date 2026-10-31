"""The installed Claude Code: where it is, its version against the floor this skill needs, login, sandbox prerequisites and usage limits."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

# The highest minimum among what the skill relies on: `--permission-prompts` and `user_message_uuids` (2.1.259), the uuid on a hook-ended result (2.1.265), `local_command` (2.1.268), and sandbox protection inside a worktree entered by `-p --resume` (2.1.314).
VERSION_FLOOR = (2, 1, 314)
VERIFIED_VERSION = (2, 1, 314)


def _text(v):
    return ".".join(str(x) for x in v)


VERSION_FLOOR_TEXT = _text(VERSION_FLOOR)


def parse_version(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def claude_version():
    """{"path", "version", "parsed", "error"} of the `claude` on PATH."""
    path = shutil.which("claude")
    if not path:
        return {"path": None, "version": None, "parsed": None, "error": "claude is not on PATH"}
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"path": path, "version": None, "parsed": None, "error": f"claude --version failed: {e}"}
    parsed = parse_version(proc.stdout)
    if proc.returncode != 0 or parsed is None:
        return {"path": path, "version": proc.stdout.strip() or None, "parsed": None, "error": f"claude --version exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:200]}"}
    return {"path": path, "version": _text(parsed), "parsed": parsed, "error": None}


def version_floor_check(info=None):
    """None when the installed claude meets the floor, otherwise why not, as one sentence."""
    info = info or claude_version()
    if info["error"]:
        return info["error"]
    if info["parsed"] < VERSION_FLOOR:
        return f"claude {info['version']} is older than {VERSION_FLOOR_TEXT}, the oldest version whose stream and sandbox behaviour this skill relies on; update Claude Code"
    return None


AUTH_FIELDS = ("loggedIn", "authMethod", "subscriptionType", "apiProvider")


def auth_status():
    """Whether claude is logged in, and how — only these fields, never the account's email or organisation."""
    import json

    path = shutil.which("claude")
    if not path:
        return {"error": "claude is not on PATH"}
    try:
        proc = subprocess.run([path, "auth", "status"], capture_output=True, text=True, timeout=30)
        data = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"error": f"claude auth status did not answer in JSON: {e}"}
    return {k: data.get(k) for k in AUTH_FIELDS}


def sandbox_prereqs():
    """What the read-only and write profiles' sandbox needs on this platform, and what is missing. A missing piece fails those runs at start, since the profiles set `failIfUnavailable`."""
    import sys

    if sys.platform == "darwin":
        needed = {"sandbox-exec": "/usr/bin/sandbox-exec"}
        missing = [n for n, p in needed.items() if not os.path.exists(p)]
    elif sys.platform.startswith("linux"):
        missing = [n for n in ("bwrap", "socat") if not shutil.which(n)]
    else:
        return {"platform": sys.platform, "supported": False, "missing": []}
    return {"platform": sys.platform, "supported": True, "missing": missing}


def parse_usage(events):
    """The `/usage` report's limits from stream-json events: per limit its kind, percent used, reset time and scope."""
    for e in events:
        report = e.get("usage_report") if isinstance(e, dict) else None
        if report is None and isinstance(e, dict) and isinstance(e.get("message"), dict):
            report = e["message"].get("usage_report")
        if not isinstance(report, dict):
            continue
        limits = []
        for item in (report.get("rate_limits") or {}).get("limits") or []:
            scope = item.get("scope") or {}
            model = (scope.get("model") or {}).get("display_name") if isinstance(scope, dict) else None
            limits.append({"kind": item.get("kind"), "percent": item.get("percent"), "resets_at": item.get("resets_at"), "scope": model, "severity": item.get("severity")})
        extra = (report.get("rate_limits") or {}).get("extra_usage") or {}
        return {"limits": limits, "extra_usage_enabled": extra.get("is_enabled")}
    return None


def quota(env):
    """The account's usage limits now, from `claude -p /usage` in safe mode (no hooks, plugins or session file; the model is not called)."""
    import json

    path = shutil.which("claude", path=env.get("PATH"))
    if not path:
        return {"error": "claude is not on PATH"}
    try:
        proc = subprocess.run([path, "-p", "--safe-mode", "--no-session-persistence", "--output-format", "stream-json", "--verbose", "/usage"], capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"claude -p /usage failed: {e}"}
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    parsed = parse_usage(events)
    if parsed is None:
        return {"error": f"claude -p /usage gave no usage report (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[-300:]}"}
    return parsed
