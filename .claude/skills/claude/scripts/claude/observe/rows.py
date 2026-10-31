"""A run as a row: its stored state, the states derived from its events (retrying, stalled), and the attention that ends a wait early."""

from __future__ import annotations

import os
from pathlib import Path

from claude.claude_cli import final_result, read_events, summarize
from claude.registry import ACTIVE, TERMINAL, claude_alive, reap
from claude.util import TIMINGS, iso, now, timings

STALL_SECONDS = int(TIMINGS["stall"])
LISTING_ROWS = 20
EXCERPT = 300


def last_event_at(run_dir, meta):
    try:
        return os.stat(Path(run_dir) / "events.jsonl").st_mtime
    except OSError:
        return meta.get("started_at") or meta.get("created_at") or now()


def attention(meta, summary, final, event_at, at, since=None):
    """Reasons a caller should look at this run now (J10): no event for the stall time, API retries going on too long, a rejected rate limit, a process still alive long after stdin closed, or a turn that ended with no reply and no hook notice."""
    t = timings()
    out = []
    state = meta.get("state")
    if state in ACTIVE:
        idle = at - max(event_at, since or 0)
        if idle >= t["stall"]:
            out.append({"reason": "stalled", "idle_seconds": round(at - event_at), "in_progress": summary["in_progress"], "note": "no event for this long; nothing is killed for it"})
        if meta.get("retrying_since") and at - meta["retrying_since"] >= t["retry_attention"]:
            out.append({"reason": "retrying", "since": iso(meta["retrying_since"]), "retry": summary["retry"]})
        rl = meta.get("rate_limit") or summary["rate_limit"]
        if rl and rl.get("status") == "rejected":
            out.append({"reason": "rate_limited", "rate_limit": rl})
        if state == "finishing" and meta.get("finishing_since") and at - meta["finishing_since"] >= t["finishing_attention"]:
            out.append({"reason": "finishing", "since": iso(meta["finishing_since"]), "tasks_open": summary["tasks_open"], "note": "the answer is in; the process is still running something after stdin closed"})
    if final["possibly_blocked"]:
        out.append({"reason": "possibly_blocked", "uuids": final["possibly_blocked"], "note": "a turn ended with no reply and no hook notice; a hook may have stopped the message"})
    return out


def display_state(meta, summary, event_at, at):
    state = meta.get("state")
    if state in ("starting", "running"):
        if summary["last_event_is_retry"]:
            return "retrying"
        if at - event_at >= timings()["stall"]:
            return "stalled"
    return state


def load(run_dir):
    """(meta after reaping, events summary, final answer, last event time) for one run."""
    meta = reap(run_dir)
    events, unparsed = read_events(Path(run_dir) / "events.jsonl")
    summary = summarize(events)
    summary["unparsed"] = unparsed
    final = final_result(events, meta.get("messages") or [])
    return meta, events, summary, final


def run_row(run_dir, at=None):
    """Everything known about one run, as `status --run` prints it."""
    at = at or now()
    meta, events, summary, final = load(run_dir)
    event_at = last_event_at(run_dir, meta)
    init = meta.get("init") or summary["init"] or {}
    row = {
        "run_id": meta["run_id"],
        "session_id": meta.get("session_id"),
        "state": display_state(meta, summary, event_at, at),
        "stored_state": meta.get("state"),
        "label": meta.get("label"),
        "group": meta.get("group"),
        "kind": meta.get("kind"),
        "profile": meta["settings"]["profile"],
        "model": init.get("model") or meta["settings"]["model"],
        "effort": meta["settings"]["effort"],
        "permission_mode": init.get("permission_mode"),
        "mode_mismatch": meta.get("mode_mismatch"),
        "cwd": init.get("cwd") or meta.get("cwd"),
        "worktree": meta.get("worktree"),
        "created": iso(meta.get("created_at")),
        "ended": iso(meta.get("ended_at")),
        "elapsed_seconds": round((meta.get("ended_at") or at) - (meta.get("created_at") or at)),
        "idle_seconds": round(at - event_at) if meta.get("state") not in TERMINAL else None,
        "exit_code": meta.get("exit_code"),
        "error": meta.get("error"),
        "attention": attention(meta, summary, final, event_at, at) or None,
        "in_progress": summary["in_progress"],
        "tasks_open": summary["tasks_open"],
        "permission_denials": summary["denials"],
        "files_edited": summary["files_edited"],
        "tool_calls": summary["tool_calls"],
        "messages": len(meta.get("messages") or []),
        "unanswered": [m["uuid"] for m in final["unanswered"]],
        "undelivered": meta.get("undelivered") or [],
        "stdin_open": bool(meta.get("stdin_open")) and meta.get("state") not in TERMINAL,
        "retrying_since": iso(meta.get("retrying_since")),
        "rate_limit": meta.get("rate_limit") or summary["rate_limit"],
        "cost_usd": summary["cost_usd"],
        "usage": summary["usage"],
        "last_message": (summary["last_message"] or "")[:EXCERPT] or None,
        "profile_exceptions": meta.get("profile_exceptions") or [],
        "unparsed_events": summary["unparsed"],
        "events": str(Path(run_dir) / "events.jsonl"),
    }
    if meta.get("state") in TERMINAL and claude_alive(meta):
        row["still_writing"] = True
    if meta.get("stderr_tail"):
        row["stderr_tail"] = meta["stderr_tail"]
    elif meta.get("state") == "failed":
        try:
            row["stderr_tail"] = (Path(run_dir) / "stderr.log").read_bytes()[-600:].decode("utf-8", "ignore").strip() or None
        except OSError:
            pass
    return row


def listing_row(row):
    keep = ("run_id", "session_id", "state", "label", "group", "profile", "model", "idle_seconds", "error", "attention")
    out = {k: row[k] for k in keep}
    out["last_message"] = (row["last_message"] or "")[:120] or None
    return out
