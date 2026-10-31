"""`status`: the listing of a project's runs, or one run's full row."""

from __future__ import annotations

from claude.registry import TERMINAL, find_run, is_live, iter_runs, list_groups, reap, resolve_runs_dir

from .rows import LISTING_ROWS, group_rows, group_state, listing_row, member_dirs, run_row


def group_status(registry, name):
    manifest, members = group_rows(registry, name)
    rows = [r for _, r in members if r]
    states = [r["stored_state"] for r in rows] + ["failed"] * sum(1 for _, r in members if r is None)
    return {
        "group": name,
        "group_state": group_state(states),
        "running": [r["run_id"] for r in rows if r["stored_state"] not in TERMINAL],
        "done": [r["run_id"] for r in rows if r["stored_state"] == "completed"],
        "failed": [r["run_id"] for r in rows if r["stored_state"] in TERMINAL and r["stored_state"] != "completed"],
        "unstarted": [{"index": m["index"], "label": m.get("label"), "error": m.get("error")} for m, r in members if r is None],
        "members": [{"index": m["index"], "label": m.get("label"), **(r or {"run_id": None, "state": None, "error": m.get("error")})} for m, r in members],
    }


def groups_summary(registry):
    out = []
    for manifest in list_groups(registry):
        states = []
        for m, d in member_dirs(registry, manifest):
            states.append(reap(d).get("state") if d else "failed")
        out.append({"group": manifest["name"], "group_state": group_state(states), "members": len(manifest.get("members") or []), "worktree": bool(manifest.get("worktree")), "created": manifest.get("created")})
    return out


def status(*, cwd, ref=None, group=None, runs_dir=None):
    registry = resolve_runs_dir(cwd, runs_dir)
    if ref:
        return run_row(find_run(registry, ref))
    if group:
        return group_status(registry, group)
    runs = iter_runs(registry)
    live, done = [], []
    for d, _ in runs:
        meta = reap(d)
        (live if is_live(meta) else done).append(d)
    shown = live + [d for d in done[::-1][:LISTING_ROWS] if d not in live]
    rows = [run_row(d) for d in shown]
    rate = [r["rate_limit"] for r in rows if r.get("rate_limit")]
    rate.sort(key=lambda x: x.get("observed_at") or 0)
    return {
        "registry": registry,
        "live": [r["run_id"] for r in rows if r["run_id"] in {d.rsplit("/", 1)[-1] for d in live}],
        "runs": [listing_row(r) for r in rows],
        "runs_truncated": max(0, len(done) - LISTING_ROWS),
        "groups": groups_summary(registry),
        "rate_limit": rate[-1] if rate else None,
    }
