"""The run commands: start a fresh session, resume one, send a message into a live run, and stop runs through their process groups."""

from __future__ import annotations

import re
import time
import uuid as uuidlib

from claude.errors import Refusal
from claude.registry import TERMINAL, claude_alive, enqueue, find_run, is_live, read_meta, reap, record_if_active, registry_args, resolve_runs_dir, supervisor_alive, update_meta
from claude.util import invocation, now, process_command, timings

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


SEND_LIMIT = 16
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def resume(*, ref, prompt, cwd, flags, label=None, timeout=None, runs_dir=None):
    """Run another turn on an existing session as a new run, re-sending its profile, model, effort and schema (a resumed `-p` session restores only its model). `ref` is a run, a session the registry knows, or the id of a session it never saw, which then needs --profile."""
    registry = resolve_runs_dir(cwd, runs_dir)
    try:
        newest = reap(find_run(registry, ref))
        session_id = newest["session_id"]
        newest = reap(find_run(registry, session_id))
    except Refusal:
        if not UUID.match(ref or ""):
            raise
        newest, session_id = None, ref
    record = None
    if newest:
        record = {**newest["settings"]}
    settings = settings_for({**flags, "resume": True}, record)
    if newest:
        run_cwd = flags.get("cwd") or newest.get("cwd")
        launch_cwd = flags.get("cwd") or newest.get("launch_cwd") or run_cwd
    else:
        run_cwd = launch_cwd = flags.get("cwd") or default_cwd(cwd)
    meta = create_run(runs_dir=registry, kind="resume", prompt=prompt, settings=settings, cwd=run_cwd, launch_cwd=launch_cwd, session_id=session_id, label=label or (newest or {}).get("label"), timeout=timeout, previous=(newest or {}).get("run_id"), group=(newest or {}).get("group"))
    reply = start_reply(meta, registry)
    if settings["changed"].get("profile"):
        reply["profile_changed_from"] = settings["changed"]["profile"]
    if newest is None:
        reply["note"] = "this session was not in the registry; it now runs under the profile you gave"
    return reply


def send_instead(run_id, meta, runs_dir):
    """What to do instead of a send the run cannot take (J16): never pointing back at send."""
    state = meta.get("state")
    extra = registry_args(runs_dir)
    if state == "finishing":
        return {"instead": invocation("result", "--run", run_id, "--wait", *extra), "or": f"{invocation('stop', '--run', run_id, *extra)}, then resume", "why": "the answer is already in and stdin is closed"}
    if state in TERMINAL and not claude_alive(meta):
        # A newer run of the same session may be live; resume would be refused for it, so point at that run instead.
        newest = reap(find_run(runs_dir, meta["session_id"])) if meta.get("session_id") else meta
        if newest.get("run_id") != run_id and is_live(newest):
            if newest.get("state") in ("starting", "running") and newest.get("stdin_open") and supervisor_alive(newest):
                return {"instead": invocation("send", newest["run_id"], "<message>", *extra), "why": f"run {run_id} has ended, but its session goes on in the live run {newest['run_id']}"}
            return send_instead(newest["run_id"], newest, runs_dir)
        return {"instead": invocation("resume", run_id, "<message>", *extra), "why": "the run has ended; resume continues its session"}
    return {"instead": f"{invocation('stop', '--run', run_id, *extra)}, then resume", "why": "the run's supervisor is gone or its stdin is closed"}


def send(*, ref, message, interrupt=False, cwd, runs_dir=None):
    """Queue `message` for a live run whose supervisor still holds stdin open, and wait briefly for the supervisor to write it. `interrupt` sends it with priority `now`, which ends the running turn; otherwise `next`, read once the running tools finish."""
    refuse_inside_worker()
    registry = resolve_runs_dir(cwd, runs_dir)
    run_dir = find_run(registry, ref)
    meta = reap(run_dir)
    run_id = meta["run_id"]
    if meta.get("state") in TERMINAL or not meta.get("stdin_open") or not supervisor_alive(meta):
        raise Refusal(f"run {run_id} is {meta.get('state')} and no longer reads messages", run_id=run_id, state=meta.get("state"), **send_instead(run_id, meta, registry))
    uid = str(uuidlib.uuid4())
    priority = "now" if interrupt else "next"
    why = enqueue(run_dir, uid, message, priority=priority, kind="send", limit=SEND_LIMIT)
    if why == "closed":
        meta = reap(run_dir)
        raise Refusal(f"run {run_id} closed its stdin before the message could be queued", run_id=run_id, state=meta.get("state"), **send_instead(run_id, meta, registry))
    if why == "limit":
        raise Refusal(f"run {run_id} already took {SEND_LIMIT} messages, the most one run accepts", run_id=run_id, instead=f"{invocation('result', '--run', run_id, '--wait', *registry_args(registry))}, then resume", why="start another turn with resume once this run ends")
    end = now() + timings()["send_wait"]
    delivered = False
    while now() < end:
        m = next((x for x in read_meta(run_dir).get("messages") or [] if x.get("uuid") == uid), None)
        if m and m.get("delivered_at"):
            delivered = True
            break
        time.sleep(0.05)
    reply = {"run_id": run_id, "message_uuid": uid, "priority": priority, "delivered": delivered}
    if not delivered:
        reply["note"] = "queued but not yet written to the worker; `status --run` shows it under `undelivered` if the supervisor dies first"
    return reply


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
