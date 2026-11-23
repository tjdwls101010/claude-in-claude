"""`clean`: remove a group's worktrees and release its name once nothing of it is left (J9).

A worktree is removed only when removing it loses nothing: no change to a tracked file, and every untracked or ignored entry either a `.worktreeinclude` copy or a startup artifact unchanged since the member's first init recorded it. `git worktree remove` would silently delete ignored files, so this check comes first. --force discards what the check would keep, but never touches live work or a branch with commits.

A caller that can ask GitHub (a schedule's Finish, K30) passes `landed`: a member whose commits are already on GitHub — merged by a pull request whose head is its last commit, or on the default branch — then goes even with something left in it, which is first kept in git under refs/claude/leftovers/<group>-<index> (`preserve_leftovers`), and its branches go with it when they point at that commit; a member whose pull request is still open stays.
"""

from __future__ import annotations

import os
from pathlib import Path

from claude.errors import Refusal
from claude.git import branch_tip, commits_beyond, current_branch, delete_branch, detached_commits, head_commit, last_changed, leftovers, preserve_leftovers, prune_worktree, unlock_and_remove
from claude.registry import find_run, group_view, is_live, iter_runs, live_runs, read_meta, reap, registry_args, release_group, session_lock
from claude.util import invocation, pid_alive, process_command


def summarize_ignored(paths):
    tops = sorted({p.split("/", 1)[0] for p in paths})
    return tops


def member_runs(runs_dir, member):
    """Every run of the member's session, newest last."""
    sid = member.get("session_id")
    return [reap(d) for d, m in iter_runs(runs_dir) if sid and m.get("session_id") == sid]


def spawning(manifest):
    """Whether the batch that wrote the manifest is still starting members: its pid alive and still this skill's batch, so a reused pid does not block clean."""
    pid = manifest.get("spawning_pid")
    if not pid or not pid_alive(pid):
        return False
    command = process_command(pid) or ""
    return "cli.py" in command and " batch" in command


def clean(*, runs_dir, name, force=False, landed=None, untouched_since=None):
    manifest = group_view(runs_dir, name)
    members = manifest.get("members") or []
    if spawning(manifest):
        raise Refusal(f"group {name} is still starting its members", live=[m.get("run_id") for m in members if m.get("run_id")], instead=invocation("stop", "--group", name, *registry_args(runs_dir)), why="wait for batch to answer, or stop the group, then clean")
    live = []
    for m in members:
        for meta in member_runs(runs_dir, m):
            if is_live(meta):
                live.append(meta["run_id"])
    if live:
        raise Refusal(f"group {name} has live runs; live work is never removed", live=live, instead=invocation("stop", "--group", name, *registry_args(runs_dir)), why="stop them first, then clean")
    removed, kept = [], []
    others = [m for _, m in live_runs(runs_dir)]
    for m in members:
        wt = m.get("worktree")
        if not wt:
            continue
        if m.get("session_id"):
            # Under the member's session lock no resume can publish a run between the liveness check and the removal (J17).
            with session_lock(runs_dir, m["session_id"]):
                clean_member(runs_dir, m, wt, others, force, removed, kept, group=name, landed=landed, untouched_since=untouched_since)
        else:
            clean_member(runs_dir, m, wt, others, force, removed, kept, group=name, landed=landed, untouched_since=untouched_since)
    released = not kept
    if released:
        release_group(runs_dir, name)
    reply = {"group": name, "removed": removed, "kept": kept, "name_released": released}
    if force:
        reply["forced"] = True
    if not released:
        reply["note"] = "the name stays reserved until every worktree is removed"
    return reply


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def clean_member(runs_dir, m, wt, others, force, removed, kept, group=None, landed=None, untouched_since=None):
    """Remove one member's worktree and branch if that loses nothing, appending to `removed` or `kept`. With `landed` (see the module docstring), a member whose commits GitHub holds goes too, after what it left is kept in git. With `untouched_since`, a worktree that changed after that time is kept: someone may be working in it."""
    path = Path(wt["path"])
    entry = {"index": m["index"], "path": str(path), "branch": wt["branch"]}
    for meta in member_runs(runs_dir, m):
        if is_live(meta):
            kept.append({**entry, "reason": f"run {meta['run_id']} of this member is live", "occupied_by": [{"run_id": meta["run_id"], "stop": invocation("stop", "--run", meta["run_id"], *registry_args(runs_dir))}]})
            return
    occupied = [o["run_id"] for o in others if o.get("cwd") and inside(o["cwd"], path)]
    if occupied:
        kept.append({**entry, "reason": "a live run outside the group works in it", "occupied_by": [{"run_id": r, "stop": invocation("stop", "--run", r, *registry_args(runs_dir))} for r in occupied]})
        return
    evidence, head, checked_out, saved = None, None, None, None
    if path.exists() and untouched_since is not None:
        changed = last_changed(str(path))
        if changed is None:
            kept.append({**entry, "reason": "git cannot read all of it, so what it holds is not known"})
            return
        if changed > untouched_since:
            kept.append({**entry, "reason": "it changed after its run ended, so someone may be working in it"})
            return
    if path.exists():
        head = head_commit(str(path))
        checked_out = current_branch(str(path))
        if landed and head and head != wt.get("base"):
            evidence = landed(head) or None
        if evidence and evidence.get("open_pr"):
            kept.append({**entry, "reason": f"its work is in pull request #{evidence['open_pr']}, which is still open; it goes once that is merged", "open_pr": evidence["open_pr"]})
            return
        if evidence and not evidence.get("landed"):
            evidence = None
        detached = detached_commits(wt["repo"], path, wt["branch"])
        if detached and not evidence:
            # Commits no branch holds would be lost with the checkout, so they are kept whatever --force says.
            kept.append({**entry, "reason": f"{detached} commit(s) on a detached HEAD that no branch holds; put them on a branch first", "instead": f"git -C {path} branch <name>"})
            return
        first = None
        if m.get("run_id"):
            try:
                first = read_meta(find_run(runs_dir, m["run_id"]))
            except Refusal:
                first = None
        artifacts = (first or {}).get("startup_artifacts") or {}
        left = leftovers(path, wt.get("repo") or wt.get("main"), artifacts)
        if left is None:
            kept.append({**entry, "reason": "git cannot read all of it (or does not see a work tree there), so what it holds is not known"})
            return
        if evidence and (left["tracked"] or left["untracked"] or left["ignored"]):
            saved = preserve_leftovers(str(path), f"refs/claude/leftovers/{group}-{m['index']}", wt.get("repo") or wt.get("main"), artifacts)
            if saved.get("kept_because"):
                kept.append({**entry, "reason": f"its work is on GitHub ({evidence['label']}), but what is left in it cannot be kept in git: {saved['kept_because']}", "landed": evidence["label"], "why": saved["kept_because"], "instead": "move what you need into your tree, or clean --force to discard it"})
                return
        elif not force and (left["tracked"] or left["untracked"] or left["ignored"]):
            reasons = []
            if left["tracked"]:
                reasons.append(f"{len(left['tracked'])} changed tracked file(s)")
            if left["untracked"]:
                reasons.append(f"{len(left['untracked'])} untracked file(s)")
            if left["ignored"]:
                reasons.append(f"ignored files under {', '.join(summarize_ignored(left['ignored']))}")
            kept.append({**entry, "reason": "it holds work removing it would lose: " + "; ".join(reasons), "tracked": left["tracked"][:20], "untracked": left["untracked"][:20], "ignored_top": summarize_ignored(left["ignored"]), "instead": "move what you need into your tree, or clean --force to discard it"})
            return
        ok, err = unlock_and_remove(wt["repo"], path, force=True)
        if not ok:
            kept.append({**entry, "reason": f"git worktree remove failed: {err}"})
            return
    else:
        # The directory was deleted by hand; git still records the worktree and would refuse to delete its branch.
        prune_worktree(wt["repo"], path)
    if evidence:
        # Its commits are on GitHub: the member's own branch, and a branch the member made and left at that commit, lose nothing. A branch that was there before the group started — a person's, or the default branch — stays, and so does any branch of a group recorded before that list was kept.
        before = wt.get("branches_before")
        deleted = []
        for b in dict.fromkeys(x for x in (wt["branch"], checked_out) if x):
            if b == evidence.get("default"):
                continue
            made_by_run = b == wt["branch"] or (before is not None and b not in before)
            if made_by_run and (branch_tip(wt["repo"], b) == head or commits_beyond(wt["repo"], b, wt["base"]) == 0):
                if delete_branch(wt["repo"], b)[0]:
                    deleted.append(b)
        out = {**entry, "landed": evidence["label"], "head": head, "branch_deleted": wt["branch"] in deleted, "branches_deleted": deleted, **({"pr": evidence["pr"]} if evidence.get("pr") else {})}
        if saved and saved.get("commit"):
            out["leftovers"] = {k: saved[k] for k in ("ref", "commit", "index_commit", "counts")}
        removed.append(out)
        return
    beyond = commits_beyond(wt["repo"], wt["branch"], wt["base"])
    if beyond:
        removed.append({**entry, "branch_kept": wt["branch"], "note": f"the branch has {beyond} commit(s) of the member's and is never deleted"})
        return
    deleted, err = delete_branch(wt["repo"], wt["branch"])
    removed.append({**entry, "branch_deleted": deleted, **({} if deleted else {"note": err})})
