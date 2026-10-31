"""`log`: what one run did, as text."""

from __future__ import annotations

from pathlib import Path

from claude.claude_cli import log_lines, read_events
from claude.registry import find_run, reap, resolve_runs_dir


def log(*, cwd, ref, runs_dir=None):
    run_dir = find_run(resolve_runs_dir(cwd, runs_dir), ref)
    meta = reap(run_dir)
    events, unparsed = read_events(Path(run_dir) / "events.jsonl")
    rel = (meta.get("init") or {}).get("cwd") or meta.get("cwd")
    lines = log_lines(events, rel_to=rel, messages=meta.get("messages") or [])
    if unparsed:
        lines.append(f"unparsed lines={unparsed}")
    lines.append(f"run={meta['run_id']} state={meta.get('state')}")
    return "\n".join(lines) + "\n"
