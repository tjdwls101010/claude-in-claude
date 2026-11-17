"""One run as structure: the header `result` prints, the final message, the structured output, and the activity rows `log` prints — what `result` and `log` render, and what a caller can read without parsing their text."""

from __future__ import annotations

from claude.claude_cli import activity_rows
from claude.registry import TERMINAL, find_run, resolve_runs_dir
from claude.util import now

from .rows import attention, last_event_at, load

BASH_NOTE = "files_edited lists Edit, Write and NotebookEdit calls; files a shell command wrote are not in it"


def snapshot_of(run_dir, attention_override=None):
    """The run in `run_dir` now. `attention_override` replaces the attention computed at this moment (a wait passes what ended it)."""
    meta, events, summary, final = load(run_dir)
    live = meta.get("state") not in TERMINAL
    # Once stdin has closed (finishing) the answer is decided (J3); whatever claude still prints is not it.
    decided = not live or meta.get("state") == "finishing"
    chosen = final["result"]
    text = chosen["text"] if chosen and decided else (summary["last_message"] or (chosen["text"] if chosen else "")) or ""
    header = {
        "run_id": meta["run_id"],
        "session_id": meta.get("session_id"),
        "state": meta.get("state"),
        "exit_code": meta.get("exit_code"),
        "error": meta.get("error"),
        "attention": attention_override or attention(meta, summary, final, last_event_at(run_dir, meta), now()) or None,
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
        header["note"] = "the answer is in and stdin is closed, but claude is still running something" if decided else "the run is live: this is its latest message, not its answer"
    schema = (meta.get("settings") or {}).get("schema_text")
    rel = (meta.get("init") or {}).get("cwd") or meta.get("cwd")
    return {
        "meta": meta,
        "header": header,
        "text": text,
        "schema": schema is not None,
        "json": chosen["structured_output"] if schema is not None and chosen and decided else None,
        "rows": activity_rows(events, rel_to=rel, messages=meta.get("messages") or []),
        "unparsed": summary["unparsed"],
        "rate_limit": meta.get("rate_limit") or summary["rate_limit"],
        "live": live,
        "decided": decided,
    }


def snapshot(*, cwd, ref, runs_dir=None):
    """The run `ref` names, as structure: `meta` (as recorded), `header` (the fields `result` prints, except `next`, the command a caller runs to wait again), `text` (the final message, or the latest one while live), `schema` (whether it is a --schema run), `json` (the structured output, None while undecided or when there is none — never an error), `rows` (`claude_cli.activity_rows`), `unparsed` (event lines that were not JSON), `rate_limit`, `live` and `decided`."""
    return snapshot_of(find_run(resolve_runs_dir(cwd, runs_dir), ref))
