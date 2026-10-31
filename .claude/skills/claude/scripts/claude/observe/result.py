"""`result`: what a run concluded — a JSON header and the final message, or one JSON document for a --schema run — at once, or after `--wait`."""

from __future__ import annotations

import json

from claude.errors import Refusal
from claude.registry import TERMINAL, find_run, resolve_runs_dir
from claude.util import invocation, now

from .rows import attention, last_event_at, load
from .wait import wait

BASH_NOTE = "files_edited lists Edit, Write and NotebookEdit calls; files a shell command wrote are not in it"


def run_result(run_dir, *, wait_reason=None, wait_attention=None, wait_timeout=None):
    meta, events, summary, final = load(run_dir)
    live = meta.get("state") not in TERMINAL
    chosen = final["result"]
    text = chosen["text"] if chosen and not live else (summary["last_message"] or (chosen["text"] if chosen else "")) or ""
    header = {
        "run_id": meta["run_id"],
        "session_id": meta.get("session_id"),
        "state": meta.get("state"),
        "exit_code": meta.get("exit_code"),
        "error": meta.get("error"),
        "attention": wait_attention or attention(meta, summary, final, last_event_at(run_dir, meta), now()) or None,
        "answered": final["answered"],
        "unanswered": final["unanswered"],
        "last_message_unanswered": final["last_message_unanswered"],
        "answer_unconfirmed": final["answer_unconfirmed"],
        "blocked_by_hook": final["blocked_by_hook"] or None,
        "last_message_blocked": final["last_message_blocked"],
        "possibly_blocked": final["possibly_blocked"] or None,
        "permission_denials": summary["denials"],
        "files_edited": summary["files_edited"],
        "files_edited_note": BASH_NOTE,
        "tool_calls": summary["tool_calls"],
        "usage": summary["usage"],
        "cost_usd": summary["cost_usd"],
        "followups": final["followups"],
        "mode_mismatch": meta.get("mode_mismatch"),
        "profile_exceptions": meta.get("profile_exceptions") or [],
        "message_bytes": len(text.encode("utf-8")),
    }
    if live:
        header["note"] = "the run is live: this is its latest message, not its answer"
        args = ["result", "--run", meta["run_id"], "--wait"]
        if wait_timeout:
            args += ["--wait-timeout", f"{wait_timeout:g}"]
        header["next"] = {"command": invocation(*args), "run_in_background": True, "why": "waits again, for the end or for attention that is new"}
    if wait_reason == "timeout":
        header["note"] = "--wait-timeout passed before the run ended; " + header.get("note", "")
    schema = (meta.get("settings") or {}).get("schema_text")
    if schema is not None:
        obj = chosen["structured_output"] if chosen and not live else None
        if not live and obj is None:
            raise Refusal("the run ended without structured output", run_id=meta["run_id"], state=meta.get("state"), message=text, error_detail=meta.get("error"))
        doc = {k: header[k] for k in ("run_id", "session_id", "state", "exit_code", "error", "attention", "permission_denials", "files_edited", "cost_usd") if k in header}
        if "note" in header:
            doc["note"] = header["note"]
            doc["next"] = header["next"]
        doc["json"] = obj
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    out = json.dumps(header, ensure_ascii=False) + "\n"
    if text:
        out += text + "\n"
    return out


def result(*, cwd, ref, wait_for=False, wait_timeout=None, runs_dir=None):
    run_dir = find_run(resolve_runs_dir(cwd, runs_dir), ref)
    if not wait_for:
        return run_result(run_dir)
    reason, fresh = wait([run_dir], timeout=wait_timeout)
    return run_result(run_dir, wait_reason=reason, wait_attention=fresh.get(run_dir), wait_timeout=wait_timeout)
