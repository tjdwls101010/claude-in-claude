"""Bringing the project's checkout up to what a schedule left on GitHub (K30). A scheduled worker merges on GitHub from a worktree it cannot leave, and `schedule`/`unschedule` commit the workflow file there, so the default branch on this Mac falls behind until someone pulls. The Finish step and the two commands call `sync_local`, which fast-forwards it (`git.sync_default`) under rules that keep it off anything of the person's: never while a run works in the checkout itself, never for a checkout whose origin is another repository, one update of a repository at a time, and with the job's tokens kept from git — gh's credential helper would otherwise authenticate with the job's token, which cannot read the repository, instead of the person's login."""

from __future__ import annotations

import os
import shlex

from claude.git import remote_url, sync_default, toplevel
from claude.github import repo_from_remote, scrub_job_env
from claude.registry import live_runs, sync_lock


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _working_here(registry, top, skip):
    """Ids of live runs whose worker works in the checkout at `top` itself rather than in a worktree of its own, leaving out the run `skip`."""
    out = []
    for _, meta in live_runs(registry):
        if meta.get("run_id") == skip or (meta.get("worktree") or {}).get("path"):
            continue
        if meta.get("cwd") and _inside(meta["cwd"], top):
            out.append(meta["run_id"])
    return out


def left_alone(path, reason, instead=None):
    """A `sync_default`-shaped reply for a checkout that was not touched."""
    return {"status": "not_updated", "path": path, "branch": None, "files_updated": False, "from": None, "to": None, "commits": [], "more": 0, "reason": reason, "files": [], "instead": instead}


def sync_local(project, registry, *, expect_repo=None, skip_run=None):
    """`git.sync_default` on the checkout at `project` — see its docstring for the reply — or, without touching git, a `not_updated` reply when the checkout's origin is not `expect_repo` (`owner/name`, any letter case) or a live run other than `skip_run` works in the checkout itself."""
    top = toplevel(project) or str(project)
    q = shlex.quote(top)
    if expect_repo:
        found = repo_from_remote(remote_url(top))
        if (found or "").lower() != expect_repo.lower():
            return left_alone(top, f"origin of this checkout is {found or 'not a GitHub repository'}, not {expect_repo}")
    busy = _working_here(registry, top, skip_run)
    if busy:
        many = len(busy) > 1
        return left_alone(top, f"run{'s' if many else ''} {', '.join(busy)} {'are' if many else 'is'} working in this checkout, and updating it would change files under {'them' if many else 'it'}", f"the next scheduled run's end tries again; or, once {'they end' if many else 'it ends'}, `git -C {q} pull --ff-only`")
    # 성진: a run started in this checkout while the update runs is not held off (starting a run does not take this lock); the window is one fetch and one fast-forward.
    with sync_lock(registry):
        return sync_default(top, env=scrub_job_env(os.environ))
