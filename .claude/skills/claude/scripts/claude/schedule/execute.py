"""A scheduled job's two steps on the runner (K1): `Run` starts the worker and holds the job until it ends; `Finish`, which GitHub runs after any end — success, failure, a cancel, a timeout — stops what is still alive, records what changed, cleans up and writes the summary.

Run, in order (K28): the project must exist (K23); a check only checks (K13); an automatic trigger decides and claims its slot (K4), any other job is recorded; refusals that cost nothing come before the worker; the worker is started under the schedule's origin; the step follows it to its end, printing its activity and warning on attention without stopping it; the exit code is the run's outcome.

Finish's stages are independent (K20): each failure is collected into the summary, and the step exits 1 only when it could not confirm the worker stopped or could not write the step summary.
"""

from __future__ import annotations

import os
import secrets
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from claude.batch import batch, clean
from claude.claude_cli import auth_status, claude_version, render_rows, sandbox_prereqs, version_floor_check
from claude.errors import Refusal
from claude.git import head_commit, numstat, status_snapshot, toplevel
from claude.github import JOB_HANDLES, annotation, job_context, resume_commands, stop_commands, write_output, write_summary
from claude.observe import snapshot, wait_ended
from claude.registry import claim_slot, claude_alive, find_by_origin_job, group_view, is_live, read_job, reap, record_job, resolve_runs_dir, schedule_dir, update_job
from claude.runs import start, stop
from claude.util import entry_path, invocation

from .summary import render_summary
from .times import current_slot

# A one-off's automatic triggers more than this after its time do nothing: GitHub drops a queued job after 24 hours, and a cron without a year would otherwise fire again a year later (K4).
ONE_OFF_EXPIRY = 26 * 3600
FOLLOW_SECONDS = 2.0
AUTOMATIC = ("dispatcher", "schedule")
RED = ("failed", "timed_out", "orphaned", "interrupted")


def clock():
    """Now, in epoch seconds; CLAUDE_SKILL_TEST_NOW fixes it in tests, as CLAUDE_SKILL_TEST_TIMINGS fixes the timings."""
    fixed = os.environ.get("CLAUDE_SKILL_TEST_NOW")
    return float(fixed) if fixed else time.time()


class Step:
    """A step's stdout: plain lines, and the step's own workflow commands. From the first line on, the runner reads no workflow command it does not get through `command` (K21), so nothing a worker writes can annotate the run, mask a value or end the step."""

    def __init__(self, write):
        self.write = write
        self.token = secrets.token_hex(12)
        self.lock = threading.Lock()
        self.say(stop_commands(self.token))

    def say(self, line):
        with self.lock:
            self.write(line + "\n")

    def command(self, line):
        with self.lock:
            self.write(f"{resume_commands(self.token)}\n{line}\n{stop_commands(self.token)}\n")


def trigger_of(ctx, source):
    """`dispatcher` or `schedule` for the two automatic triggers, `re-run` for any attempt after the first (it is someone pressing Re-run, whatever the first attempt was), `manual` otherwise."""
    if ctx["attempt"] > 1:
        return "re-run"
    if ctx["event"] == "schedule":
        return "schedule"
    if source == "dispatcher":
        return "dispatcher"
    return "manual"


def local_time(ts, tz):
    d = datetime.fromtimestamp(ts, ZoneInfo(tz))
    return f"{d.strftime('%Y-%m-%d %H:%M')} {d.tzname()}"


def at_instant(spec):
    return int(datetime.strptime(spec["at"], "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo(spec["timezone"])).timestamp())


def run_checks(spec):
    """What a scheduled worker needs on this runner, checked without starting one (K13)."""
    checks = []
    info = claude_version()
    problem = version_floor_check(info)
    checks.append({"name": "claude", "ok": not problem, "detail": problem or f"{info['path']} {info['version']}"})
    if not info["error"]:
        auth = auth_status()
        ok = bool(auth.get("loggedIn"))
        checks.append({"name": "login", "ok": ok, "detail": auth.get("error") or (f"logged in ({auth.get('authMethod')}, {auth.get('subscriptionType')})" if ok else f"claude is not logged in (authMethod {auth.get('authMethod')}): the runner's service cannot read the login")})
    if spec["settings"]["profile"] in ("read-only", "write"):
        sb = sandbox_prereqs()
        ok = sb["supported"] and not sb["missing"]
        checks.append({"name": "sandbox", "ok": ok, "detail": "available" if ok else (f"missing {', '.join(sb['missing'])}" if sb["supported"] else f"not supported on {sb['platform']}")})
    uv = shutil.which("uv")
    checks.append({"name": "uv", "ok": bool(uv), "detail": uv or "uv is not on the runner's PATH"})
    project = spec["project"]
    checks.append({"name": "project", "ok": True, "detail": project + ("" if toplevel(project) else " (not a git checkout)")})
    if spec.get("worktree"):
        ok = bool(head_commit(project))
        checks.append({"name": "worktree", "ok": ok, "detail": "the repository has a commit to start from" if ok else "--worktree needs a commit to start from"})
    return {"kind": "check", "ok": all(c["ok"] for c in checks), "checks": checks}


def _scrub_worker_env():
    """K9: the worker and its supervisor inherit this process's environment, so the job's handles go before the worker starts."""
    for key in list(os.environ):
        if key in JOB_HANDLES or key.startswith("CLAUDE_SCHEDULE_"):
            del os.environ[key]


def _start_worker(spec, prompt, schema_path, registry, ctx, origin):
    """Start the worker as `start` would, or as a one-member `batch --worktree` group (K10). Returns (run_id, group, refusal)."""
    s = spec["settings"]
    if spec.get("worktree"):
        group = f"{spec['name']}-{ctx['run_id']}-{ctx['attempt']}"
        reply = batch(name=group, task_args=[prompt], tasks_file=None, defaults={"profile": s["profile"], "model": s["model"], "effort": s["effort"], "schema": schema_path, "timeout": s["timeout"], "cwd": None}, cwd=spec["project"], use_worktrees=True, runs_dir=registry, origin=origin)
        member = (reply.get("runs") or [{}])[0]
        if not member.get("run_id"):
            return None, group, member.get("error") or "the worktree member did not start"
        return member["run_id"], group, None
    reply = start(prompt=prompt, cwd=spec["project"], flags={"profile": s["profile"], "model": s["model"], "effort": s["effort"], "schema": schema_path, "cwd": spec["project"]}, label=spec["name"], timeout=s["timeout"], runs_dir=registry, origin=origin)
    return reply["run_id"], None, None


def _follow(run_id, registry, step, stop_event):
    """Print the run's activity as `log` lines while it runs (K1)."""
    printed = 0
    while True:
        try:
            rows = [r for r in snapshot(cwd=registry, ref=run_id, runs_dir=registry)["rows"] if r["kind"] != "running"]
        except Refusal:
            rows = []
        # 성진: every poll re-reads the whole events file; read it incrementally if long runs make the step slow.
        for line in render_rows(rows[printed:]):
            step.say(line)
        printed = max(printed, len(rows))
        if stop_event.is_set():
            return
        stop_event.wait(FOLLOW_SECONDS)


def scheduled_run(spec, env, write):
    """The Run step. `spec` holds name, project, settings (profile, model, effort, timeout), cron or at, timezone and worktree; `env` is the job's environment; `write` takes stdout text. Returns the exit code: 0 when the worker completed (with structured output for a schema run), a late duplicate was skipped, or a check passed; 1 otherwise."""
    step = Step(write)
    name = spec["name"]
    ctx = job_context(env)
    if ctx is None:
        step.command(annotation("error", name, "__scheduled runs inside a GitHub Actions job; GITHUB_RUN_ID is not set"))
        return 1
    project = spec["project"]
    if not Path(project).is_dir():
        # K23: nothing is written, since the registry would be created at a path that no longer exists.
        step.command(annotation("error", f"{name}: project missing", f"{project} is not a directory on this runner; if the project moved, run `schedule --name {name} --project <new path>` again"))
        return 1
    registry = resolve_runs_dir(project)
    job = ctx["job"]
    mode = env.get("CLAUDE_SCHEDULE_MODE") or "run"
    if mode == "check":
        outcome = run_checks(spec)
        record_job(registry, name, job, {"trigger": "manual", "mode": "check", "url": ctx["url"], "outcome": outcome})
        for c in outcome["checks"]:
            step.say(f"check {c['name']} {'ok' if c['ok'] else 'FAILED'} {c['detail']}")
        if not outcome["ok"]:
            step.command(annotation("error", f"{name}: check failed", "; ".join(c["detail"] for c in outcome["checks"] if not c["ok"])))
        return 0 if outcome["ok"] else 1

    trigger = trigger_of(ctx, env.get("CLAUDE_SCHEDULE_SOURCE") or "")
    s = spec["settings"]
    worktree_group = f"{name}-{ctx['run_id']}-{ctx['attempt']}" if spec.get("worktree") else None
    entry = {"trigger": trigger, "mode": "run", "profile": s["profile"], "url": ctx["url"], "attempt": ctx["attempt"], "group": worktree_group, "tree_before": None if spec.get("worktree") else status_snapshot(project), "outcome": None}
    slot = retry_of = None
    if trigger in AUTOMATIC:
        now = clock()
        if spec.get("at") and now - at_instant(spec) > ONE_OFF_EXPIRY:
            record_job(registry, name, job, {**entry, "outcome": {"kind": "skipped", "reason": f"the one-off time {spec['at']} passed more than 26 hours ago"}})
            step.say(f"skipped: the one-off time {spec['at']} passed more than 26 hours ago")
            return 0
        slot = current_slot(spec, now)
        if slot is None:
            record_job(registry, name, job, {**entry, "outcome": {"kind": "skipped", "reason": f"the one-off time {spec['at']} has not come"}})
            step.say(f"skipped: the one-off time {spec['at']} has not come; only a manual run starts it early")
            return 0
        claim = claim_slot(registry, name, slot, job, entry)
        if claim["decision"] == "skip":
            prev = claim["previous"] or {}
            step.say(f"skipped: slot {local_time(slot, spec['timezone'])} already ran" + (f" in {prev.get('url')} ({prev.get('state')})" if prev.get("url") else ""))
            return 0
        if claim["decision"] == "retry":
            retry_of = claim["previous"]
            step.say(f"retrying slot {local_time(slot, spec['timezone'])}: the run that took it ended {retry_of.get('state')}")
    else:
        record_job(registry, name, job, entry)

    if spec.get("worktree") and not head_commit(project):
        error = "--worktree needs a commit to start from, and this repository has none; the worker was not started"
        update_job(registry, name, job, {"outcome": {"kind": "refused", "error": error}})
        step.command(annotation("error", f"{name}: not started", error))
        return 1
    prompt = env.get("CLAUDE_SCHEDULE_PROMPT") or ""
    schema_path = None
    if env.get("CLAUDE_SCHEDULE_SCHEMA"):
        # K22: the workflow carries the schema's text; the worker gets it as a file of this job's.
        schema_path = str(Path(schedule_dir(registry, name)) / f"schema-{job}.json")
        Path(schema_path).parent.mkdir(parents=True, exist_ok=True)
        Path(schema_path).write_text(env["CLAUDE_SCHEDULE_SCHEMA"], encoding="utf-8")
    origin = {"kind": "schedule", "name": name, "trigger": trigger, "slot": slot, "job": job, "url": ctx["url"], "repository": ctx["repository"], "when": local_time(slot if slot is not None else clock(), spec["timezone"])}
    if retry_of:
        origin["retry_of"] = retry_of["job"]
    _scrub_worker_env()
    try:
        run_id, group, refused = _start_worker(spec, prompt, schema_path, registry, ctx, origin)
    except Refusal as e:
        run_id, group, refused = None, worktree_group, e.message
    if refused:
        update_job(registry, name, job, {"outcome": {"kind": "refused", "error": refused}})
        step.command(annotation("error", f"{name}: not started", refused))
        return 1
    # Also by id, so Finish finds the run even when its meta.json no longer parses.
    update_job(registry, name, job, {"run_id": run_id})
    step.say(f"run {run_id} · {s['profile']} · {s['model']}/{s['effort']} · {trigger}" + (f" · slot {local_time(slot, spec['timezone'])}" if slot is not None else ""))
    done = threading.Event()
    follower = threading.Thread(target=_follow, args=(run_id, registry, step, done), daemon=True)
    follower.start()
    seen = []

    def on_attention(items):
        for a in items:
            seen.append({"reason": a["reason"], "at": local_time(clock(), spec["timezone"])})
            step.command(annotation("warning", f"{name}: {a['reason']}", a.get("note") or a["reason"]))
        update_job(registry, name, job, {"attention": seen})

    final = wait_ended(cwd=registry, ref=run_id, runs_dir=registry, on_attention=on_attention)
    done.set()
    follower.join(timeout=FOLLOW_SECONDS * 3)
    state = final["meta"].get("state")
    ok = state == "completed" and (not final["schema"] or final["json"] is not None)
    step.say(f"run={run_id} state={state}" + ("" if ok or state != "completed" else " (no structured output)"))
    return 0 if ok else 1


def _changes(spec, rec, meta, edited):
    """What changed during the run (K27): against the snapshot the Run step took before the worker, for a run in the project checkout; everything in its worktree, which starts clean. `edited` (the edit tools' files) stands in where git cannot tell."""
    wt = meta.get("worktree")
    if wt and wt.get("path"):
        snap = status_snapshot(wt["path"])
        if snap is None:
            return {"where": "the worktree", "kind": "worktree", "files": []}
        paths = sorted(snap["entries"])
        counts = numstat(wt["path"], [p for p in paths if snap["entries"][p]["status"] != "??"])
        return {"where": "the worktree", "kind": "worktree", "files": [_file(wt["path"], p, snap["entries"][p], counts) for p in paths]}
    project = spec["project"]
    before = (rec or {}).get("tree_before")
    after = status_snapshot(project)
    if after is None or before is None:
        return {"where": "the project directory", "not_git": list(edited), "files": []}
    paths = sorted(p for p in set(before["entries"]) | set(after["entries"]) if before["entries"].get(p) != after["entries"].get(p))
    fresh = [p for p in paths if p in after["entries"] and p not in before["entries"] and after["entries"][p]["status"] != "??"]
    counts = numstat(project, fresh)
    files = []
    for p in paths:
        if p not in after["entries"]:
            files.append({"status": "  ", "path": p, "note": "no longer changed: reverted or committed"})
        elif p in before["entries"]:
            files.append({"status": after["entries"][p]["status"], "path": p, "note": "already modified before the run"})
        else:
            files.append(_file(project, p, after["entries"][p], counts))
    if (before.get("head"), before.get("branch")) != (after.get("head"), after.get("branch")):
        files.append({"status": "->", "path": f"{before.get('branch') or 'detached'} @ {(before.get('head') or '')[:7]} → {after.get('branch') or 'detached'} @ {(after.get('head') or '')[:7]}", "note": "HEAD moved during the run"})
    return {"where": "the project checkout", "files": files}


def _file(root, rel, entry, counts):
    f = {"status": entry["status"], "path": rel}
    if entry["status"] == "??":
        try:
            f["new_lines"] = len((Path(root) / rel).read_bytes().splitlines())
        except OSError:
            pass
    elif counts.get(rel):
        f["lines"] = counts[rel]
    return f


def _tree(spec, rec, meta):
    wt = (meta or {}).get("worktree")
    if wt and wt.get("path"):
        return {"kind": "worktree", "path": wt["path"], "branch": wt.get("branch"), "base": wt.get("base")}
    before = (rec or {}).get("tree_before")
    if before is None:
        return {"kind": "none", "path": spec["project"]}
    return {"kind": "checkout", "branch": before.get("branch"), "head": before.get("head"), "uncommitted_before": len(before.get("entries") or {})}


def _render_kept(snap, context, warnings, local):
    """Render the summary and keep a copy at `local` (K17); a copy that cannot be written becomes one more warning in what GitHub gets."""
    text = render_summary(snap, {**context, "warnings": warnings})
    if local is None:
        return text
    try:
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_text(text, encoding="utf-8")
    except OSError as e:
        text = render_summary(snap, {**context, "warnings": warnings + [f"The local copy of this summary could not be written: {e}"]})
    return text


def _post(step, name, ctx, text):
    """Write the step summary; 1 when it cannot be written (K20)."""
    path = ctx.get("summary_path")
    try:
        if not path:
            raise OSError("the runner gave no GITHUB_STEP_SUMMARY")
        write_summary(path, text)
    except OSError as e:
        step.command(annotation("error", f"{name}: summary not written", str(e)))
        return 1
    return 0


def scheduled_finish(spec, env, write):
    """The Finish step, run after any end of the job (K20): stop a worker still alive, read what changed, clean up a worktree that holds nothing, keep the summary beside the run and post it to the job. Returns 1 only when the worker could not be confirmed stopped or the step summary could not be written; every other failure is a warning in the summary."""
    step = Step(write)
    name, project = spec["name"], spec["project"]
    ctx = job_context(env) or {}
    job = ctx.get("job")
    base = {"name": name, "timezone": spec["timezone"], "prompt": env.get("CLAUDE_SCHEDULE_PROMPT")}
    if not Path(project).is_dir():
        # K23: no registry to keep anything in; GitHub gets the summary.
        text = render_summary(None, {**base, "at": clock(), "outcome": {"kind": "missing", "title": "project missing", "error": f"{project} is not a directory on this runner.", "instead": f"If the project moved, run `schedule --name {name} --project <new path>` again."}})
        return _post(step, name, ctx, text)
    registry = resolve_runs_dir(project)
    rec = (read_job(registry, name, job) if job else None) or {}
    trigger = {"kind": rec.get("trigger") or (trigger_of(ctx, env.get("CLAUDE_SCHEDULE_SOURCE") or "") if ctx else "manual"), "attempt": ctx.get("attempt")}
    if rec.get("retry_of"):
        earlier = find_by_origin_job(registry, rec["retry_of"])
        trigger["retry_of_url"] = (reap(earlier[-1]).get("origin") or {}).get("url") if earlier else None
    base.update({"trigger": trigger, "slot": rec.get("slot")})
    local = str(Path(schedule_dir(registry, name)) / f"summary-{job}.md")
    outcome = rec.get("outcome") or {}
    if (env.get("CLAUDE_SCHEDULE_MODE") or "run") == "check" or outcome.get("kind") in ("check", "skipped", "refused"):
        if not outcome:
            outcome = {"kind": "check", "ok": False, "checks": [{"name": "check", "ok": False, "detail": "the Run step recorded no result; read its log"}]}
        text = _render_kept(None, {**base, "at": rec.get("at") or clock(), "outcome": outcome, "prompt": None if outcome["kind"] == "check" else base["prompt"]}, [], local)
        if outcome["kind"] == "refused" or (outcome["kind"] == "check" and not outcome.get("ok")):
            step.command(annotation("error", f"{name} failed", outcome.get("error") or "the check failed"))
        return _post(step, name, ctx, text)
    runs = find_by_origin_job(registry, job) if job else []
    if not runs and rec.get("run_id") and (Path(registry) / rec["run_id"]).is_dir():
        runs = [str(Path(registry) / rec["run_id"])]
    if not runs:
        text = _render_kept(None, {**base, "at": clock(), "outcome": {"kind": "none", "title": "no worker", "error": "The Run step did not start a worker.", "instead": "Its step log above says why."}}, [], local)
        step.command(annotation("error", f"{name} failed", "the Run step did not start a worker"))
        return _post(step, name, ctx, text)

    run_dir = runs[-1]
    run_id = Path(run_dir).name
    warnings, unconfirmed, stopped_by_finish = [], None, False
    try:
        meta = reap(run_dir)
    except Refusal as e:
        meta, unconfirmed = None, f"its meta.json cannot be read ({e.message}), so whether the worker still runs is unknown"
    if meta is not None and is_live(meta):
        # The Run step was cancelled or timed out with the worker alive; the runner would kill it as the job ends and leave the run orphaned (probe 5).
        stopped_by_finish = True
        try:
            stop(refs=[run_id], cwd=project, runs_dir=registry)
        except Refusal as e:
            warnings.append(f"Stopping the worker failed: {e.message}")
        meta = reap(run_dir)
        if is_live(meta) or claude_alive(meta):
            unconfirmed = f"run {run_id} is still {meta.get('state')} after stop"
    snap = None
    if meta is not None:
        try:
            snap = snapshot(cwd=registry, ref=run_id, runs_dir=registry)
        except Refusal as e:
            unconfirmed = unconfirmed or f"the run cannot be read: {e.message}"
    changes = None
    if meta is not None:
        try:
            changes = _changes(spec, rec, meta, (snap or {}).get("header", {}).get("files_edited") or [])
        except OSError as e:
            warnings.append(f"What changed could not be read: {e}")
    group = rec.get("group")
    if group and changes is not None:
        # K10: only a group this job created is cleaned; a name some other batch holds is left alone.
        try:
            if (group_view(registry, group).get("origin") or {}).get("job") == job:
                result = clean(name=group, cwd=project, runs_dir=registry)
                if result["kept"]:
                    k = result["kept"][0]
                    changes["kept"] = {"path": k["path"], "branch": k["branch"], "clean": invocation("clean", "--group", group, "--project", project)}
                else:
                    changes["removed"] = True
        except Refusal as e:
            warnings.append(f"The worktree was not cleaned up ({e.message}); `{invocation('clean', '--group', group, '--project', project)}` does it.")
    if unconfirmed:
        warnings.insert(0, f"**The worker could not be confirmed stopped:** {unconfirmed}. Check this Mac, and `{invocation('stop', '--run', run_id, '--project', project)}`.")
    rel = os.path.relpath(run_dir, project)
    context = {**base, "tree": _tree(spec, rec, meta), "changes": changes, "attention": rec.get("attention") or [], "stopped_by_finish": stopped_by_finish, "continue": {"cli": entry_path(), "project": project, "run_dir": (run_dir if rel.startswith("..") else rel) + "/"}, "log_call": invocation("log", "--run", run_id, "--project", project)}
    if snap is None:
        context.update({"at": clock(), "outcome": {"kind": "none", "title": "unreadable run", "error": f"Run {run_id} cannot be read."}})
    text = _render_kept(snap, context, warnings, str(Path(run_dir) / "summary.md"))
    code = _post(step, name, ctx, text)
    state = (meta or {}).get("state")
    if ctx.get("output_path"):
        try:
            write_output(ctx["output_path"], {"run_id": run_id, "state": state})
        except OSError:
            pass
    if (state in RED and not stopped_by_finish) or (snap is not None and state == "completed" and snap["schema"] and snap["json"] is None):
        step.command(annotation("error", f"{name} failed", (meta or {}).get("error") or state))
    if unconfirmed:
        step.command(annotation("error", f"{name}: worker not confirmed stopped", unconfirmed))
        code = 1
    return code
