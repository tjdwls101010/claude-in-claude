"""The installed Claude Code: where it is, its version against the floor this skill needs, login, sandbox prerequisites and usage limits."""

from __future__ import annotations

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
