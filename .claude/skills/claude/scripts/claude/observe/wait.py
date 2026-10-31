"""Waiting on runs: until each has ended, or until one needs attention that was not there when the wait began."""

from __future__ import annotations

import time

from claude.registry import TERMINAL
from claude.util import now, timings

from .rows import attention, last_event_at, load


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
            if meta.get("state") not in TERMINAL:
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
