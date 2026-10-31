"""The run commands: start a fresh session, and stop runs through their process groups."""

from __future__ import annotations

import time

from claude.errors import Refusal
from claude.registry import TERMINAL, claude_alive, find_run, read_meta, reap, record_if_active, resolve_runs_dir, update_meta
from claude.util import now, process_command, timings

from .create import create_run, default_cwd, refuse_inside_worker, start_reply
from .settings import settings_for
from .supervisor import signal_ladder


def start(*, prompt, cwd, flags, label=None, timeout=None, runs_dir=None):
    """Start a fresh worker session on `prompt`. `cwd` is where the command was run; `flags` holds profile, model, effort, schema and an explicit run directory (`cwd` key) when given."""
    settings = settings_for(flags)
    run_cwd = flags.get("cwd") or default_cwd(cwd)
    # The registry belongs to the project the command runs in, so `status` there finds the run whatever --cwd says.
    registry = resolve_runs_dir(cwd, runs_dir)
    meta = create_run(runs_dir=registry, kind="start", prompt=prompt, settings=settings, cwd=run_cwd, label=label, timeout=timeout)
    return start_reply(meta, registry)


def stop_one(run_dir):
    meta = reap(run_dir)
    entry = {"run_id": meta["run_id"], "session_id": meta.get("session_id"), "signals_sent": []}
    still = claude_alive(meta)
    if meta.get("state") in TERMINAL and not still:
        entry.update({"state": meta["state"], "note": "already ended"})
        return entry
    if meta.get("state") not in TERMINAL:
        update_meta(run_dir, lambda m: m.update({"stop_requested": now()}) if m.get("state") not in TERMINAL else None)
    pgid, pid = meta.get("claude_pgid"), meta.get("claude_pid")
    command = process_command(pid) if pid else None
    if pgid and pid and still and not ("claude" in (command or "") and "stream-json" in (command or "")):
        # meta.json lies inside a writer's working directory; never signal a process group that is not the claude this run started.
        entry.update({"state": meta.get("state"), "note": f"the recorded process {pid} is not claude ({(command or '?')[:80]}); not signalled"})
        return entry
    if pgid and pid:
        entry["signals_sent"] = signal_ladder(pgid, pid)
    # The supervisor records the outcome once claude exits; when it is gone, record it here.
    end = now() + timings()["kill_grace"] + 5
    while now() < end:
        meta = reap(run_dir)
        if meta.get("state") in TERMINAL:
            break
        time.sleep(0.05)
    if meta.get("state") not in TERMINAL:
        record_if_active(run_dir, {"state": "interrupted", "error": "stopped", "ended_at": now(), "stdin_open": False})
        meta = read_meta(run_dir)
    entry["state"] = meta.get("state")
    return entry


def stop(*, refs=(), cwd, runs_dir=None, run_dirs=None):
    """Stop each run named in `refs` (or each directory in `run_dirs`): SIGINT to its process group, then SIGTERM, then SIGKILL, so Claude Code can end the turn and keep the session resumable."""
    refuse_inside_worker()
    registry = resolve_runs_dir(cwd, runs_dir)
    dirs = list(run_dirs or []) + [find_run(registry, r) for r in refs]
    if not dirs:
        raise Refusal("nothing to stop", arguments=True, help="stop --help")
    return {"stopped": [stop_one(d) for d in dirs]}
