"""`status`: the listing of a project's runs, or one run's full row."""

from __future__ import annotations

from claude.registry import find_run, is_live, iter_runs, reap, resolve_runs_dir

from .rows import LISTING_ROWS, listing_row, run_row


def status(*, cwd, ref=None, runs_dir=None):
    registry = resolve_runs_dir(cwd, runs_dir)
    if ref:
        return run_row(find_run(registry, ref))
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
        "groups": [],
        "rate_limit": rate[-1] if rate else None,
    }
