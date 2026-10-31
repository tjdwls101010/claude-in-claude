"""Helpers every unit shares: time, text trimming, process liveness, the skill's own invocation string, and timings."""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Production timings in seconds. CLAUDE_SKILL_TEST_TIMINGS (a JSON object) overrides any of them, so the test suite does not wait out real grace periods.
TIMINGS = {
    "idle_grace": 10.0,  # stdout silence after the last answer before stdin is closed (J1 b)
    "init_wait": 15.0,  # how long `start` waits for the first init before answering
    "send_wait": 10.0,  # how long `send` waits for the supervisor to deliver
    "stop_grace": 10.0,  # SIGINT → SIGTERM
    "kill_grace": 3.0,  # SIGTERM → SIGKILL
    "stall": 600.0,  # no event this long is attention
    "retry_attention": 120.0,  # API retries this long is attention
    "finishing_attention": 120.0,  # a process alive this long after stdin closed is attention
    "poll": 0.2,
}


def timings():
    t = dict(TIMINGS)
    raw = os.environ.get("CLAUDE_SKILL_TEST_TIMINGS")
    if raw:
        try:
            t.update({k: float(v) for k, v in json.loads(raw).items() if k in TIMINGS})
        except (ValueError, TypeError, AttributeError):
            pass
    return t


def now():
    return time.time()


def iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def nfc(text):
    return unicodedata.normalize("NFC", text)


def trim_bytes(text, limit):
    """`text` cut to at most `limit` UTF-8 bytes at a character boundary."""
    data = text.encode("utf-8", "replace")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore")


def pid_alive(pid, pgid=None):
    """Whether `pid` is running and, when `pgid` is given, still in that process group, which tells a reused pid apart."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if pgid is not None:
        try:
            return os.getpgid(pid) == pgid
        except OSError:
            return False
    try:
        # A zombie still answers kill(0); reap it if it is our child, and treat it as gone.
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True
    except OSError:
        return True


def group_alive(pgid):
    if not pgid:
        return False
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def entry_path():
    """The path `cli.py` was run as, symlinks kept: a pre-approval names the installed path, not where a link points."""
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None) or sys.argv[0]
    return os.path.abspath(path)


def invocation(*args):
    """The command line that runs this skill with `args`, written the way its pre-approval pattern matches: `uv run "<cli.py>" …`."""
    import shlex

    # The entry path is always double-quoted, as the pre-approval pattern writes it; the rest is quoted only where a shell needs it.
    return " ".join(["uv run", f'"{entry_path()}"', *(a if a.startswith("<") else shlex.quote(a) for a in args)])


def process_command(pid):
    """The command line of process `pid` as `ps` reports it, or None."""
    import subprocess

    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out or None


def skill_dir():
    return str(Path(entry_path()).parent.parent)
