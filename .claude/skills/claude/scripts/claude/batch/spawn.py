"""Starting a group's members: which members get a worktree (J8), the facts each member is told, and starting them side by side."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from claude.claude_cli import worktree_location
from claude.errors import Refusal
from claude.git import branch_exists, head_commit, main_checkout, toplevel, uncommitted_count
from claude.runs import create_run, resume, settings_for, start_reply

WRITERS = ("write", "auto")


def plan_members(group, tasks, defaults, caller_cwd, use_worktrees):
    """Each member's settings, directory and worktree, decided before anything starts. A fresh member gets a worktree when --worktree is on, its profile can write, it names no cwd of its own, and the repository has a commit to start from."""
    repo = toplevel(caller_cwd)
    head = head_commit(repo) if repo else None
    plans = []
    for i, task in enumerate(tasks, 1):
        flags = {k: task.get(k) or defaults.get(k) for k in ("profile", "model", "effort", "schema")}
        plan = {"index": i, "task": task, "label": task.get("label"), "kind": task["kind"], "worktree": None}
        if task["kind"] == "start":
            plan["settings"] = settings_for(flags)
            plan["cwd"] = str(Path(task["cwd"]).expanduser().resolve()) if task.get("cwd") else (defaults.get("cwd") or repo or str(Path(caller_cwd).resolve()))
            if use_worktrees and plan["settings"]["profile"] in WRITERS and not task.get("cwd") and not defaults.get("cwd") and repo and head:
                name = f"{group}-{i}"
                where = worktree_location(repo, name)
                plan["worktree"] = {"name": name, "path": where["path"], "branch": where["branch"], "base": head, "repo": repo, "main": main_checkout(repo) or repo}
        else:
            plan["flags"] = flags
        plans.append(plan)
    for p in plans:
        wt = p["worktree"]
        if wt and (Path(wt["path"]).exists() or branch_exists(wt["repo"], wt["branch"])):
            raise Refusal(f"worktree {wt['name']} is still there from an earlier group (path {wt['path']} or branch {wt['branch']}); Claude Code would reopen it instead of starting fresh", path=wt["path"], branch=wt["branch"], instead="clean that group, or choose another group name")
    return plans, {"repo": repo, "head": head, "uncommitted": uncommitted_count(repo) if repo else None}


def start_member(runs_dir, group, size, plan, defaults, caller_cwd, facts):
    """Start one member; returns its manifest entry and its reply row. A member that fails to start keeps its slot with an `error`."""
    entry = {"index": plan["index"], "label": plan["label"], "kind": plan["kind"], "run_id": None, "session_id": None, "worktree": plan["worktree"], "error": None}
    group_info = {"name": group, "index": plan["index"], "size": size}
    task = plan["task"]
    try:
        if plan["kind"] == "start":
            wt = plan["worktree"]
            wt_info = {"path": wt["path"], "base": wt["base"], "uncommitted": facts["uncommitted"]} if wt else None
            meta = create_run(
                runs_dir=runs_dir, kind="start", prompt=task["prompt"], settings=plan["settings"], cwd=wt["repo"] if wt else plan["cwd"], launch_cwd=wt["repo"] if wt else None,
                label=plan["label"] or group, timeout=defaults.get("timeout"), group=group, worktree=wt["name"] if wt else None,
                group_info=group_info, worktree_info=wt_info, extra_meta={"worktree": wt, "group_index": plan["index"]} if wt else {"group_index": plan["index"]},
            )
            reply = start_reply(meta, runs_dir)
        else:
            reply = resume(ref=task["resume"], prompt=task["prompt"], cwd=caller_cwd, flags={**plan["flags"], "cwd": None}, label=plan["label"], timeout=defaults.get("timeout"), runs_dir=runs_dir, group=group, group_info=group_info, group_index=plan["index"])
    except Refusal as e:
        entry["error"] = e.message
        return entry, {"index": plan["index"], "label": plan["label"], "run_id": None, "error": e.message, **{k: v for k, v in e.fields.items() if k in ("instead", "run_id")}}
    entry.update({"run_id": reply["run_id"], "session_id": reply["session_id"], "error": reply.get("error")})
    row = {"index": plan["index"], "label": plan["label"], "run_id": reply["run_id"], "state": reply["state"], "cwd": reply["cwd"], "worktree": plan["worktree"]["path"] if plan["worktree"] else None, "profile": reply["profile"], "error": reply.get("error")}
    return entry, row


def start_members(runs_dir, group, plans, defaults, caller_cwd, facts):
    """Start every member at once, so N members cost one init wait, not N."""
    with ThreadPoolExecutor(max_workers=min(8, len(plans))) as pool:
        futures = [pool.submit(start_member, runs_dir, group, len(plans), p, defaults, caller_cwd, facts) for p in plans]
        return [f.result() for f in futures]
