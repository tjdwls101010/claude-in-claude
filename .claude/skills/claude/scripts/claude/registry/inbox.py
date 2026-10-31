"""The queue between `send` and a run's supervisor. Putting a message in, the supervisor taking messages out to write them to stdin, and closing stdin all happen under the run's lock, so a message put in is either delivered or still in the inbox when the supervisor dies — never dropped by a close.

The run's meta carries `stdin_open` and the `messages` list (one entry per message: uuid, head, priority, kind, and once delivered `delivered_at` and `after_line`, the number of stdout lines read when it was written).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from claude.util import now

from .locks import write_json
from .runs import meta_path, read_meta, run_lock


def _inbox(run_dir):
    return Path(run_dir) / "inbox"


def enqueue(run_dir, uuid, text, *, priority=None, kind="send", limit=None):
    """Put a message in the inbox while stdin is open. Returns None when queued, otherwise why not: `closed`, or `limit` when the run already took `limit` sends."""
    with run_lock(run_dir):
        meta = read_meta(run_dir)
        if not meta.get("stdin_open"):
            return "closed"
        messages = meta.setdefault("messages", [])
        if limit is not None and kind == "send" and sum(1 for m in messages if m.get("kind") == "send") >= limit:
            return "limit"
        _inbox(run_dir).mkdir(exist_ok=True)
        name = f"{time.time_ns():020d}-{uuid}.json"
        write_json(_inbox(run_dir) / name, {"uuid": uuid, "text": text, "priority": priority, "kind": kind})
        messages.append({"uuid": uuid, "head": text[:80], "bytes": len(text.encode("utf-8")), "priority": priority, "kind": kind, "enqueued_at": now(), "delivered_at": None, "after_line": None})
        write_json(meta_path(run_dir), meta)
        return None


def pending(run_dir):
    return sorted(_inbox(run_dir).glob("*.json")) if _inbox(run_dir).is_dir() else []


def take(run_dir, deliver, lines_read):
    """Hand every queued message, oldest first, to `deliver(message)` (which writes it to stdin) and record its delivery. `lines_read()` is the stdout line count at the moment of writing. Returns the messages delivered."""
    with run_lock(run_dir):
        files = pending(run_dir)
        if not files:
            return []
        meta = read_meta(run_dir)
        delivered = []
        for f in files:
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                f.unlink(missing_ok=True)
                continue
            at = lines_read()
            deliver(msg)
            f.unlink(missing_ok=True)
            for m in meta.setdefault("messages", []):
                if m.get("uuid") == msg["uuid"]:
                    m["delivered_at"] = now()
                    m["after_line"] = at
            delivered.append(msg)
        write_json(meta_path(run_dir), meta)
        return delivered


def close(run_dir, decide):
    """Close the run's stdin if the inbox is empty and `decide(meta)` agrees, recording it in meta; `decide` runs under the lock, so no message can arrive between the decision and the close. True when closed."""
    with run_lock(run_dir):
        if pending(run_dir):
            return False
        meta = read_meta(run_dir)
        if not meta.get("stdin_open"):
            return True
        if not decide(meta):
            return False
        meta["stdin_open"] = False
        meta["stdin_closed_at"] = now()
        write_json(meta_path(run_dir), meta)
        return True
