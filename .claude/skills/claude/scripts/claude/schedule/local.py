"""Bringing the project's checkout up to what a schedule left on GitHub (K30). A scheduled worker merges on GitHub from a worktree it cannot leave, and `schedule`/`unschedule` commit the workflow file there, so the default branch on this Mac falls behind until someone pulls. The Finish step and the two commands call `sync_local`, which fast-forwards it (`git.sync_default`) under rules that keep it off anything of the person's: never while a run works in the checkout itself or while a scheduled run that did has not had its changes read by its Finish (a Run step also holds the lock from its snapshot until its worker is live) (checked before the fetch and again right before anything changes), never for a checkout whose origin is another repository, one update of a repository at a time, and with the job's handles kept from every git command — gh's credential helper would otherwise authenticate with the job's token, which cannot read the repository, instead of the person's login."""

from __future__ import annotations

import os
import shlex
import time

from claude.git import remote_url, sync_default, toplevel
from claude.github import repo_from_remote, scrub_job_env
from claude.registry import is_live, iter_runs, reap, sync_lock

# How long after its end a scheduled run that worked in the checkout keeps holding updates off while its Finish has not read what it changed: Finish follows Run within seconds, and a job killed before Finish must not hold the checkout for ever.
AWAITING_FINISH_SECONDS = 15 * 60


def _works_in(cwd, top, env):
    """Whether a run whose directory is `cwd` works in the checkout at `top`: git places that directory in this checkout, not in a worktree or repository of its own below it, compared as the file system sees it (a Mac's ignores letter case)."""
    try:
        own = toplevel(cwd, env=env) if os.path.isdir(cwd) else None
        return bool(own) and os.path.samefile(own, top)
    except OSError:
        return False


def _holding(registry, top, skip, env):
    """Why an update of the checkout at `top` must wait, or None: a live run whose worker works in that checkout itself rather than in a worktree of its own, or a scheduled run that did whose Finish has not yet read what it changed (K27; `changes_read_at` in its meta), if it ended within AWAITING_FINISH_SECONDS — leaving out the run `skip`."""
    # 성진: only runs in this registry are seen; a run started with --runs-dir elsewhere works in the checkout unseen, as it is to `start`'s check for concurrent writers.
    for run_dir, meta in iter_runs(registry):
        if meta.get("run_id") == skip or (meta.get("worktree") or {}).get("path") or not meta.get("cwd"):
            continue
        meta = reap(run_dir)
        if is_live(meta):
            why = f"run {meta['run_id']} is working in this checkout, and updating it would change files under it"
        elif (meta.get("origin") or {}).get("kind") == "schedule" and not meta.get("changes_read_at") and time.time() - (meta.get("ended_at") or 0) < AWAITING_FINISH_SECONDS:
            why = f"scheduled run {meta['run_id']} worked in this checkout and its job has not read what it changed yet"
        else:
            continue
        if _works_in(meta["cwd"], top, env):
            return why
    return None


def left_alone(path, reason, instead=None):
    """A `sync_default`-shaped reply for a checkout that was not touched."""
    return {"status": "not_updated", "path": path, "branch": None, "files_updated": False, "from": None, "to": None, "commits": [], "more": 0, "reason": reason, "files": [], "instead": instead}


def sync_local(project, registry, *, expect_repo=None, skip_run=None):
    """`git.sync_default` on the checkout at `project` — see its docstring for the reply — or, without changing anything, a `not_updated` reply when the checkout's origin is not `expect_repo` (`owner/name`, any letter case) or a run other than `skip_run` holds it (see `_holding`)."""
    env = scrub_job_env(os.environ)
    top = toplevel(project, env=env) or str(project)
    q = shlex.quote(top)
    if expect_repo:
        found = repo_from_remote(remote_url(top, env=env))
        if (found or "").lower() != expect_repo.lower():
            return left_alone(top, f"origin of this checkout is {found or 'not a GitHub repository'}, not {expect_repo}", f"`git -C {q} remote -v` shows it; point origin at {expect_repo}, or `schedule --no-pull` this schedule")
    held = _holding(registry, top, skip_run, env)
    if held:
        return left_alone(top, held, "the next scheduled run's end tries again once it is over")
    with sync_lock(registry):
        return sync_default(top, env=env, guard=lambda: _holding(registry, top, skip_run, env))
