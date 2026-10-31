"""`batch` and `clean`: several runs as one named group, and removing what the group left behind."""

from __future__ import annotations

from claude.errors import Refusal
from claude.registry import claim_group, record_members, registry_args, resolve_runs_dir, valid_group_name
from claude.runs import refuse_inside_worker
from claude.util import invocation

from .clean import clean as clean_group
from .spawn import plan_members, start_members
from .tasks import parse_tasks


def batch(*, name, task_args, tasks_file, defaults, cwd, use_worktrees=False, runs_dir=None):
    """Start every task as a member of group `name`. The name stays reserved until `clean` releases it."""
    refuse_inside_worker()
    if not valid_group_name(name):
        raise Refusal(f"group name {name!r}: lowercase letters, digits and hyphens, starting with a letter or digit, at most 40", arguments=True, help="batch --help")
    tasks = parse_tasks(task_args, tasks_file)
    registry = resolve_runs_dir(cwd, runs_dir)
    plans, facts = plan_members(name, tasks, defaults, cwd, use_worktrees)
    claim_group(registry, name, {"size": len(plans), "worktree": use_worktrees, "base": facts["head"], "repo": facts["repo"]})
    results = start_members(registry, name, plans, defaults, cwd, facts)
    record_members(registry, name, [entry for entry, _ in results])
    rows = [row for _, row in results]
    spawned = sum(1 for r in rows if r.get("run_id"))
    reply = {"group": name, "spawned": spawned, "requested": len(plans), "runs": rows}
    if spawned:
        reply["next"] = {"command": invocation("result", "--group", name, "--wait", *registry_args(registry)), "run_in_background": True, "why": "returns when every member has ended or one needs attention, and prints each member's result"}
    isolated = [p for p in plans if p["worktree"]]
    if isolated:
        reply["worktrees"] = {"base": facts["head"], "uncommitted_in_your_tree": facts["uncommitted"], "note": "each worktree starts from your local HEAD without your uncommitted changes, and holds only what git tracks plus .worktreeinclude copies; moving changes back into your tree is yours to do, then `clean`"}
    else:
        writers = [r for r in rows if r.get("run_id") and r.get("profile") != "read-only"]
        if len(writers) > 1:
            reply["shared_tree"] = "several members can write in the same directory and cannot tell each other's edits apart; --worktree isolates fresh writers"
    return reply


def clean(*, name, cwd, force=False, runs_dir=None):
    refuse_inside_worker()
    return clean_group(runs_dir=resolve_runs_dir(cwd, runs_dir), name=name, force=force)
