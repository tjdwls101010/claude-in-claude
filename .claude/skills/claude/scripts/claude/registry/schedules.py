"""Schedule state under <registry>/.schedules/<name>/: state.json, which holds the slot automatic triggers last filled (K4), who filled each recent slot and whether it was retried, and each job's hand-over from its Run step to its Finish step (K19) — plus the files a scheduled run keeps beside it. Every write happens under the schedule's lock.

A job is one attempt of one GitHub Actions run, keyed `<run id>-<attempt>`. The state file is a cache of what the runs' own `origin` records: when it is lost, the slot claims and retries are rebuilt from them (a refusal that left no run cannot be).
"""

from __future__ import annotations

from pathlib import Path

from claude.util import now

from .locks import locked, read_json, write_json
from .runs import TERMINAL, ensure_runs_dir, is_live, iter_runs, reap

KEEP = 50
NOT_COMPLETED = ("failed", "timed_out", "orphaned")


def schedule_dir(registry, name):
    """Where schedule `name` keeps its state and files."""
    return str(Path(registry) / ".schedules" / name)


def _state_path(registry, name):
    return Path(schedule_dir(registry, name)) / "state.json"


def _lock(registry, name):
    return locked(Path(registry) / ".locks" / f"schedule-{name}.lock")


def schedule_state(registry, name):
    """The schedule's state as stored, or None when there is none."""
    return read_json(_state_path(registry, name))


def _schedule_runs(registry, name):
    """(run_dir, meta) of every run this schedule started, oldest first."""
    return [(d, m) for d, m in iter_runs(registry) if (m.get("origin") or {}).get("kind") == "schedule" and m["origin"].get("name") == name]


def _rebuild(registry, name):
    """The state as the runs' origins record it: which job filled each slot, which retried it, and the latest slot."""
    state = {"name": name, "last_slot": None, "slots": {}, "jobs": {}}
    for _, m in _schedule_runs(registry, name):
        o = m["origin"]
        if o.get("slot") is None:
            continue
        claim = state["slots"].setdefault(str(o["slot"]), {"job": None, "retried": None})
        if o.get("retry_of"):
            claim["retried"] = o["job"]
            claim["job"] = claim["job"] or o["retry_of"]
        else:
            claim["job"] = o["job"]
        state["last_slot"] = max(state["last_slot"] or 0, o["slot"])
    return state


def _load(registry, name):
    return schedule_state(registry, name) or _rebuild(registry, name)


def _prune(state):
    for key in ("slots", "jobs"):
        items = state.get(key) or {}
        if len(items) > KEEP:
            order = sorted(items, key=lambda k: (items[k].get("at") or 0, k)) if key == "jobs" else sorted(items, key=int)
            for k in order[: len(items) - KEEP]:
                del items[k]


def _save(registry, name, state):
    ensure_runs_dir(registry)
    Path(schedule_dir(registry, name)).mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    _prune(state)
    write_json(_state_path(registry, name), state)


def _job_run(registry, name, job):
    """The newest run job `job` started, reaped, or None."""
    found = [d for d, m in _schedule_runs(registry, name) if m["origin"].get("job") == job]
    return reap(found[-1]) if found else None


def _completed_or_live(registry, name, state, job):
    """Whether the job that filled a slot got somewhere that a retry must not repeat: its run completed, was stopped, or is still live. A refusal before any run, and a run that failed, timed out or was orphaned, did not."""
    meta = _job_run(registry, name, job)
    if meta is None:
        return ((state["jobs"].get(job) or {}).get("outcome") or {}).get("kind") != "refused"
    if is_live(meta) or meta.get("state") not in TERMINAL:
        return True
    return meta.get("state") not in NOT_COMPLETED


def _profile_of(registry, name, state, job):
    """The profile job `job` ran under: a slot is retried only when the job that failed it was read-only, whatever the schedule says now."""
    rec = state["jobs"].get(job) or {}
    if rec.get("profile"):
        return rec["profile"]
    meta = _job_run(registry, name, job)
    return ((meta or {}).get("settings") or {}).get("profile")


def _previous(registry, name, state, job):
    meta = _job_run(registry, name, job) if job else None
    rec = state["jobs"].get(job) or {}
    return {"job": job, "run_id": meta["run_id"] if meta else None, "state": meta.get("state") if meta else (rec.get("outcome") or {}).get("kind"), "url": ((meta or {}).get("origin") or {}).get("url") or rec.get("url")}


def claim_slot(registry, name, slot, job, entry):
    """Decide, under the schedule's lock, what an automatic trigger for `slot` does (K4), and record job `job` with `entry` (K19 ①). Returns `decision` — `first` (the slot was free and is now this job's), `retry` (the read-only job that filled it did not complete and has not been retried, and this job is read-only too: it is that slot's one retry) or `skip` (it is filled, or a later slot already ran) — and `previous`, the job that filled it with its run id, state and run URL. `entry` must carry `profile`; a skipped job is recorded with outcome `skipped`."""
    with _lock(registry, name):
        state = _load(registry, name)
        claim = state["slots"].get(str(slot))
        rec = {**entry, "slot": slot, "at": now()}
        if state["last_slot"] is None or slot > state["last_slot"]:
            state["last_slot"] = slot
            state["slots"][str(slot)] = {"job": job, "retried": None}
            decision, previous = "first", None
        elif claim and claim.get("job") and slot == state["last_slot"] and not claim.get("retried") and entry.get("profile") == "read-only" and _profile_of(registry, name, state, claim["job"]) == "read-only" and not _completed_or_live(registry, name, state, claim["job"]):
            claim["retried"] = job
            rec["retry_of"] = claim["job"]
            decision, previous = "retry", _previous(registry, name, state, claim["job"])
        else:
            decision = "skip"
            previous = _previous(registry, name, state, claim.get("job")) if claim else None
            rec["outcome"] = {"kind": "skipped", "previous": previous, "reason": "this slot already ran" if claim else "a later slot already ran"}
        state["jobs"][job] = rec
        _save(registry, name, state)
        return {"decision": decision, "previous": previous}


def record_job(registry, name, job, entry):
    """Record a job that claims no slot (a manual run, a re-run, a check), leaving the slots alone."""
    with _lock(registry, name):
        state = _load(registry, name)
        state["jobs"][job] = {**entry, "at": now()}
        _save(registry, name, state)


def update_job(registry, name, job, fields):
    """Merge `fields` into job `job`'s record, creating it if needed. Returns the record."""
    with _lock(registry, name):
        state = _load(registry, name)
        rec = state["jobs"].setdefault(job, {"at": now()})
        rec.update(fields)
        _save(registry, name, state)
        return rec


def read_job(registry, name, job):
    """Job `job`'s record, or None."""
    state = schedule_state(registry, name)
    return ((state or {}).get("jobs") or {}).get(job)


def find_by_origin_job(registry, job):
    """The run directories whose meta's `origin.job` is `job`, oldest first."""
    return [d for d, m in iter_runs(registry) if (m.get("origin") or {}).get("job") == job]
