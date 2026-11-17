"""`result`: what a run concluded — a JSON header and the final message, or one JSON document for a --schema run — at once, or after `--wait`."""

from __future__ import annotations

import json
from pathlib import Path

from claude.errors import Refusal
from claude.registry import TERMINAL, find_run, group_view, is_live, registry_args, resolve_runs_dir
from claude.util import invocation, now, trim_bytes

from .rows import attention, group_state, last_event_at, load, member_dirs
from .snapshot import snapshot_of
from .wait import wait

def registry_of(run_dir):
    return str(Path(run_dir).parent)


def run_result(run_dir, *, wait_reason=None, wait_attention=None, wait_timeout=None):
    snap = snapshot_of(run_dir, attention_override=wait_attention)
    meta, header, text = snap["meta"], snap["header"], snap["text"]
    if snap["live"]:
        args = ["result", "--run", meta["run_id"], "--wait", *registry_args(registry_of(run_dir))]
        if wait_timeout:
            args += ["--wait-timeout", f"{wait_timeout:g}"]
        header["next"] = {"command": invocation(*args), "run_in_background": True, "why": "waits again, for the end or for attention that is new"}
    if wait_reason == "timeout":
        header["note"] = "--wait-timeout passed before the run ended; " + header.get("note", "")
    if snap["schema"]:
        obj = snap["json"]
        if not snap["live"] and obj is None:
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


GROUP_MESSAGE_CAP = 4000


def group_result(registry, name, *, wait_reason=None, fresh=None, wait_timeout=None):
    """A group's header, then each member's final message capped at GROUP_MESSAGE_CAP bytes behind a separator line."""
    manifest = group_view(registry, name)
    members = member_dirs(registry, manifest)
    rows, sections, edited, cost = [], [], {}, 0.0
    states = []
    attention_members = []
    for m, d in members:
        tag = f"{m['index']}:{m['label']}" if m.get("label") else str(m["index"])
        if d is None:
            rows.append({"index": m["index"], "label": m.get("label"), "run_id": None, "state": None, "error": m.get("error")})
            states.append("failed")
            continue
        meta, _, summary, final = load(d)
        decided = meta.get("state") in TERMINAL or meta.get("state") == "finishing"
        chosen = final["result"]
        text = chosen["text"] if chosen and decided else (summary["last_message"] or "")
        shown = trim_bytes(text, GROUP_MESSAGE_CAP)
        att = (fresh or {}).get(d) or attention(meta, summary, final, last_event_at(d, meta), now()) or None
        if att:
            attention_members.append({"index": m["index"], "run_id": meta["run_id"], "attention": att})
        for path in summary["files_edited"]:
            edited.setdefault(path, []).append(m["index"])
        cost += summary["cost_usd"] or 0
        states.append("running" if is_live(meta) else meta.get("state"))
        rows.append({"index": m["index"], "label": m.get("label"), "run_id": meta["run_id"], "state": meta.get("state"), "error": meta.get("error"), "bytes": len(text.encode("utf-8")), "shown_bytes": len(shown.encode("utf-8")), "files_edited": len(summary["files_edited"]), "permission_denials": len(summary["denials"]), "worktree": (meta.get("worktree") or {}).get("path")})
        sections.append(f"--- [{tag}] run={meta['run_id']} state={meta.get('state')} bytes={len(text.encode('utf-8'))}\n" + (shown + "\n" if shown else ""))
    header = {
        "group": name,
        "group_state": group_state(states),
        "overlaps": {p: ix for p, ix in edited.items() if len(ix) > 1},
        "totals": {"members": len(members), "completed": states.count("completed"), "failed": sum(1 for s in states if s in TERMINAL and s != "completed"), "running": sum(1 for s in states if s not in TERMINAL), "cost_usd": round(cost, 6)},
        "attention": attention_members or None,
        "members": rows,
    }
    if header["group_state"] == "running":
        args = ["result", "--group", name, "--wait", *registry_args(registry)]
        if wait_timeout:
            args += ["--wait-timeout", f"{wait_timeout:g}"]
        header["next"] = {"command": invocation(*args), "run_in_background": True, "why": "waits again, for every member to end or for attention that is new"}
        header["note"] = "members are still live: their messages are partial"
    if wait_reason == "timeout":
        header["note"] = "--wait-timeout passed before every member ended; " + header.get("note", "")
    return json.dumps(header, ensure_ascii=False) + "\n" + "".join(sections)


def result(*, cwd, ref=None, group=None, wait_for=False, wait_timeout=None, runs_dir=None):
    registry = resolve_runs_dir(cwd, runs_dir)
    if group:
        if not wait_for:
            return group_result(registry, group)
        dirs = [d for _, d in member_dirs(registry, group_view(registry, group)) if d]
        reason, fresh = wait(dirs, timeout=wait_timeout)
        return group_result(registry, group, wait_reason=reason, fresh=fresh, wait_timeout=wait_timeout)
    run_dir = find_run(registry, ref)
    if not wait_for:
        return run_result(run_dir)
    reason, fresh = wait([run_dir], timeout=wait_timeout)
    return run_result(run_dir, wait_reason=reason, wait_attention=fresh.get(run_dir), wait_timeout=wait_timeout)
