"""Waiting on runs: until each has ended, or until one needs attention that was not there when the wait began."""

from __future__ import annotations

import time

from claude.registry import TERMINAL, claude_alive, find_run, resolve_runs_dir
from claude.util import now, timings

from .rows import attention, last_event_at, load
from .snapshot import snapshot_of


def wait(run_dirs, timeout=None):
    """Block until every run in `run_dirs` has ended, a new attention appears on any of them, or `timeout` seconds pass. Returns (reason, {run_dir: [attention…]}) with reason `ended`, `attention` or `timeout`.

    Attention already present when the wait begins does not end it, so waiting again on a run that needs attention waits for something new; a stall counts afresh from the start of the wait."""
    t = timings()
    began = now()
    seen = {}
    for d in run_dirs:
        meta, _, summary, final = load(d)
        seen[d] = {a["reason"] for a in attention(meta, summary, final, last_event_at(d, meta), began) if a["reason"] != "stalled"}
    while True:
        at = now()
        ended = True
        fresh = {}
        for d in run_dirs:
            meta, _, summary, final = load(d)
            # A run whose claude still writes after its supervisor died has not ended (J16).
            if meta.get("state") not in TERMINAL or claude_alive(meta):
                ended = False
            current = attention(meta, summary, final, last_event_at(d, meta), at, since=began)
            reasons = {a["reason"] for a in current}
            seen[d] &= reasons
            new = [a for a in current if a["reason"] not in seen[d]]
            if new and meta.get("state") not in TERMINAL:
                fresh[d] = new
        if ended:
            return "ended", {}
        if fresh:
            return "attention", fresh
        if timeout is not None and at - began >= timeout:
            return "timeout", {}
        time.sleep(max(t["poll"], 0.05))



def wait_ended(*, cwd, ref, runs_dir=None, on_attention=None):
    """Block until the run `ref` names has ended, whatever attention it needs meanwhile. `on_attention(items)` is called with each attention reason as it appears; a reason that lasts — one long stall — is reported once, and again only after it has cleared. Returns the ended run's `snapshot`."""
    run_dir = find_run(resolve_runs_dir(cwd, runs_dir), ref)
    t = timings()
    reported = set()
    while True:
        meta, _, summary, final = load(run_dir)
        if meta.get("state") in TERMINAL and not claude_alive(meta):
            return snapshot_of(run_dir)
        current = attention(meta, summary, final, last_event_at(run_dir, meta), now()) if meta.get("state") not in TERMINAL else []
        reasons = {a["reason"] for a in current}
        new = [a for a in current if a["reason"] not in reported]
        reported = reasons
        if new and on_attention:
            on_attention(new)
        time.sleep(max(t["poll"], 0.05))
