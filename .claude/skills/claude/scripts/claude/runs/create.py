"""Creating a run in four steps: refusals that cost nothing (recursion, the claude version), publishing the run under its session's lock, spawning the detached supervisor, and waiting briefly for the first init so a start that fails says so in its reply."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid as uuidlib
from pathlib import Path

from claude.claude_cli import build_argv, profile_exceptions, turn_preamble, version_floor_check
from claude.errors import Refusal
from claude.git import main_checkout, toplevel
from claude.registry import TERMINAL, claude_alive, enqueue, is_live, live_runs, publish_run, read_meta, registry_args, supervisor_alive, update_meta
from claude.util import entry_path, invocation, now, timings

RUN_VARIABLE = "CLAUDE_SKILL_RUN"


def refuse_inside_worker():
    """A worker cannot start, steer or stop workers (J6)."""
    if os.environ.get(RUN_VARIABLE):
        raise Refusal(f"this command runs inside worker run {os.environ[RUN_VARIABLE]}; a worker cannot start, steer, stop or clean workers", inside_run=os.environ[RUN_VARIABLE])


def live_instead(run_id, meta, runs_dir):
    """What to do instead of starting another run on a session that has a live one (J16): send to it while its stdin is open, otherwise stop it first."""
    extra = registry_args(runs_dir)
    if meta.get("state") in ("starting", "running") and meta.get("stdin_open") and supervisor_alive(meta):
        return {"instead": invocation("send", run_id, "<message>", *extra), "why": "the run is live and still reading messages"}
    return {"instead": f"{invocation('stop', '--run', run_id, *extra)}, then resume", "why": "the run is finishing or its supervisor is gone while claude still runs"}


def refuse_live(runs_dir):
    def check(existing):
        for meta in existing:
            if is_live(meta):
                raise Refusal(f"session {meta.get('session_id')} has a live run {meta.get('run_id')} ({meta.get('state')}{', still writing' if meta.get('state') in TERMINAL else ''}); two processes on one session mix their transcripts", run_id=meta.get("run_id"), state=meta.get("state"), **live_instead(meta.get("run_id"), meta, runs_dir))

    return check


def default_cwd(cwd):
    return toplevel(cwd) or str(Path(cwd).resolve())


def spawn_supervisor(run_dir):
    log = open(Path(run_dir) / "supervisor.log", "ab")
    proc = subprocess.Popen([sys.executable, entry_path(), "__supervise", "--run-dir", run_dir], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True, close_fds=True)
    log.close()
    return proc.pid


def wait_for_init(run_dir, seconds):
    """Wait until the run reports its first init or ends, or `seconds` pass. Returns its meta."""
    end = now() + seconds
    meta = read_meta(run_dir)
    while now() < end:
        meta = read_meta(run_dir)
        if meta.get("init") or meta.get("state") in TERMINAL:
            return meta
        time.sleep(0.05)
    return meta


def concurrent_writers(runs_dir, cwd, run_id):
    out = []
    for d, m in live_runs(runs_dir):
        if m.get("run_id") != run_id and (m.get("settings") or {}).get("profile") != "read-only" and os.path.realpath(m.get("cwd") or "") == os.path.realpath(cwd):
            out.append(m.get("run_id"))
    return out


def create_run(*, runs_dir, kind, prompt, settings, cwd, session_id=None, label=None, timeout=None, previous=None, group=None, worktree=None, expect_cwd=None, launch_cwd=None, group_info=None, worktree_info=None, extra_meta=None, precheck=None, on_published=None):
    """Publish and start one run. `kind` is `start` (a new session) or `resume` (`session_id` given). Returns the run's meta after the init wait."""
    refuse_inside_worker()
    problem = version_floor_check()
    if problem:
        raise Refusal(problem)
    session_id = session_id or str(uuidlib.uuid4())
    launch_cwd = launch_cwd or cwd
    # Facts that can change from turn to turn (the profile, a group, a worktree) go in front of the prompt, not into the system prompt, which a resumed session keeps as first recorded.
    preamble = turn_preamble(settings["profile"], group=group_info, worktree=worktree_info)
    text = f"{preamble}\n\n{prompt}" if preamble else prompt
    argv = build_argv(settings, session_id=session_id, resume=kind == "resume", cwd=cwd, worktree=worktree, schema_text=settings.get("schema_text"))
    roots = [r for r in {toplevel(cwd), main_checkout(cwd)} if r]

    def make_meta(run_id, run_dir):
        meta = {
            "run_id": run_id,
            "session_id": session_id,
            "kind": kind,
            "label": label,
            "group": group,
            "state": "starting",
            "cwd": cwd,
            "launch_cwd": launch_cwd,
            "expect_cwd": expect_cwd,
            "worktree": None,
            "settings": {"profile": settings["profile"], "model": settings["model"], "effort": settings["effort"], "schema_text": settings.get("schema_text"), "timeout": timeout},
            "argv": argv,
            "stdin_open": True,
            "messages": [],
            "previous_run": previous,
            "caller_session_id": os.environ.get("CLAUDE_CODE_SESSION_ID"),
            "profile_exceptions": profile_exceptions(cwd, settings["profile"], project_roots=roots),
        }
        meta.update(extra_meta or {})
        return meta

    live_check = refuse_live(runs_dir)

    def check(existing):
        live_check(existing)
        if precheck:
            precheck()

    run_id, run_dir, meta = publish_run(runs_dir, session_id, label, check, make_meta)
    if on_published:
        on_published(meta)
    enqueue(run_dir, str(uuidlib.uuid4()), text, kind="prompt", head=prompt)
    pid = spawn_supervisor(run_dir)
    update_meta(run_dir, lambda m: (m.setdefault("supervisor_pid", pid), m.setdefault("supervisor_pgid", pid)))
    return wait_for_init(run_dir, timings()["init_wait"])


def start_reply(meta, runs_dir):
    """The JSON a starting command prints for one run."""
    init = meta.get("init") or {}
    reply = {
        "run_id": meta["run_id"],
        "session_id": meta["session_id"],
        "state": meta.get("state"),
        "next": {"command": invocation("result", "--run", meta["run_id"], "--wait", *registry_args(runs_dir)), "run_in_background": True, "why": "returns when the run ends or needs attention, and prints its result"},
        "profile": meta["settings"]["profile"],
        "permission_mode": init.get("permission_mode"),
        "mode_mismatch": meta.get("mode_mismatch"),
        "model": init.get("model") or meta["settings"]["model"],
        "effort": meta["settings"]["effort"],
        "cwd": init.get("cwd") or meta["cwd"],
        "concurrent_writers": concurrent_writers(runs_dir, meta["cwd"], meta["run_id"]) if meta["settings"]["profile"] != "read-only" else [],
        "profile_exceptions": meta.get("profile_exceptions") or [],
        "events": str(Path(runs_dir) / meta["run_id"] / "events.jsonl"),
    }
    if not meta.get("init") and meta.get("state") not in TERMINAL:
        reply["note"] = "claude has not reported its init yet; `status --run` shows it once it does"
    if meta.get("state") == "failed":
        reply["error"] = meta.get("error")
        if meta.get("stderr_tail"):
            reply["stderr_tail"] = meta["stderr_tail"]
        reply.pop("next")
    return reply
