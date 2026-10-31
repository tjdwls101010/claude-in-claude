"""Run directories under <main checkout>/.claude-runs: claiming one, its meta.json written atomically under the run's lock, compare-and-set for outcomes, reaping a run whose supervisor died, and finding a run by id, session or prefix."""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

from claude.errors import Refusal
from claude.git import main_checkout
from claude.util import iso, now, pid_alive

from .locks import locked, read_json, write_json

DIRNAME = ".claude-runs"
TERMINAL = ("completed", "failed", "interrupted", "timed_out", "orphaned")
ACTIVE = ("starting", "running", "finishing")
# A run published but never handed to a supervisor (its creator died in between) is orphaned after this long.
UNSUPERVISED_GRACE = 60.0


def resolve_runs_dir(cwd, runs_dir=None):
    """The registry for work started from `cwd`: `runs_dir` when given, otherwise .claude-runs in the repository's main checkout, so every worktree of a repository shares one; outside git, in `cwd` itself."""
    if runs_dir:
        return str(Path(runs_dir).expanduser().resolve())
    base = main_checkout(cwd) or str(Path(cwd).resolve())
    return str(Path(base) / DIRNAME)


def registry_args(runs_dir):
    """`--runs-dir <dir>` when `runs_dir` is not the registry a command run from the current directory would find, so a printed command reaches the same runs wherever it is run; nothing otherwise."""
    if os.path.realpath(runs_dir) == os.path.realpath(resolve_runs_dir(os.getcwd())):
        return []
    return ["--runs-dir", str(runs_dir)]


def ensure_runs_dir(runs_dir):
    """Create the registry if needed, with a .gitignore of `*` so git never sees it."""
    path = Path(runs_dir)
    (path / ".locks").mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n")
    return str(path)


def meta_path(run_dir):
    return Path(run_dir) / "meta.json"


def run_lock(run_dir):
    return locked(Path(run_dir) / ".lock")


def read_meta(run_dir):
    """A run's meta.json; Refusal when it is missing or does not parse."""
    try:
        meta = read_json(meta_path(run_dir))
    except ValueError as e:
        raise Refusal(f"meta.json of {Path(run_dir).name} does not parse: {e}")
    if meta is None:
        raise Refusal(f"no run at {run_dir}")
    return meta


def update_meta(run_dir, change):
    """Apply `change(meta)` under the run's lock and write the result; `change` edits the dict in place. Returns the new meta."""
    with run_lock(run_dir):
        meta = read_meta(run_dir)
        change(meta)
        write_json(meta_path(run_dir), meta)
        return meta


def record_if_active(run_dir, fields):
    """Write `fields` only while the run has not recorded an outcome, so the first outcome written wins. True when written."""
    with run_lock(run_dir):
        meta = read_meta(run_dir)
        if meta.get("state") in TERMINAL:
            return False
        meta.update(fields)
        write_json(meta_path(run_dir), meta)
        return True


def supervisor_alive(meta):
    return pid_alive(meta.get("supervisor_pid"), meta.get("supervisor_pgid"))


def claude_alive(meta):
    return pid_alive(meta.get("claude_pid"), meta.get("claude_pgid"))


def is_live(meta):
    """Whether anything of the run may still be working: an outcome not yet recorded, or the recorded claude process still running in its own process group (an orphan still writing)."""
    return meta.get("state") not in TERMINAL or claude_alive(meta)


def reap(run_dir):
    """Record `orphaned` for a run whose supervisor is gone without recording an outcome, with what it left undelivered. Returns the meta as it now stands."""
    meta = read_meta(run_dir)
    if meta.get("state") in TERMINAL:
        return meta
    if meta.get("supervisor_pid"):
        if supervisor_alive(meta):
            return meta
    elif now() - (meta.get("created_at") or 0) < UNSUPERVISED_GRACE:
        return meta
    inbox = sorted(p.name for p in (Path(run_dir) / "inbox").glob("*.json")) if (Path(run_dir) / "inbox").is_dir() else []
    fields = {"state": "orphaned", "ended_at": now(), "error": "the supervisor died before recording an outcome", "undelivered": [n.split("-", 1)[1][:-5] for n in inbox]}
    record_if_active(run_dir, fields)
    return read_meta(run_dir)


def new_run_id(label=None):
    slug = re.sub(r"[^a-z0-9-]+", "-", (label or "run").lower()).strip("-")[:24] or "run"
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}-{secrets.token_hex(2)}"


def publish_run(runs_dir, session_id, label, check, make_meta):
    """Create a run for `session_id` under the session's lock: `check(existing metas of that session)` may refuse, then a fresh run directory is claimed and `make_meta(run_id, run_dir)` written as its meta.json. Returns (run_id, run_dir, meta)."""
    ensure_runs_dir(runs_dir)
    with locked(Path(runs_dir) / ".locks" / f"session-{session_id}.lock"):
        check([reap(d) for d, m in iter_runs(runs_dir) if m.get("session_id") == session_id])
        for _ in range(20):
            run_id = new_run_id(label)
            run_dir = Path(runs_dir) / run_id
            try:
                run_dir.mkdir()
                break
            except FileExistsError:
                continue
        else:
            raise Refusal("could not claim a free run id")
        (run_dir / "inbox").mkdir()
        meta = make_meta(run_id, str(run_dir))
        meta.setdefault("run_id", run_id)
        meta.setdefault("created_at", now())
        meta.setdefault("created", iso(meta["created_at"]))
        write_json(meta_path(run_dir), meta)
        return run_id, str(run_dir), meta


def iter_runs(runs_dir):
    """(run_dir, meta) for every readable run, oldest first. A meta.json that does not parse is skipped here; `find_run` names it."""
    path = Path(runs_dir)
    if not path.is_dir():
        return []
    out = []
    for d in path.iterdir():
        if d.name.startswith(".") or not d.is_dir():
            continue
        try:
            meta = read_json(d / "meta.json")
        except ValueError:
            continue
        if meta:
            out.append((str(d), meta))
    out.sort(key=lambda x: (x[1].get("created_at") or 0, Path(x[0]).name))
    return out


def find_run(runs_dir, ref):
    """The run directory `ref` names: a run id, a session id (its newest run), or a prefix of either that picks one run or one session. Refusal otherwise."""
    if not ref:
        raise Refusal("no run named", arguments=True)
    exact = Path(runs_dir) / ref
    if (exact / "meta.json").exists():
        return str(exact)
    runs = iter_runs(runs_dir)
    by_session = [d for d, m in runs if m.get("session_id") == ref]
    if by_session:
        return by_session[-1]
    ids = [d for d, m in runs if Path(d).name.startswith(ref)]
    sessions = {m.get("session_id") for d, m in runs if (m.get("session_id") or "").startswith(ref)}
    if len(ids) == 1 and not sessions - {read_json(Path(ids[0]) / "meta.json").get("session_id")}:
        return ids[0]
    if not ids and len(sessions) == 1:
        sid = sessions.pop()
        return [d for d, m in runs if m.get("session_id") == sid][-1]
    if ids or sessions:
        raise Refusal(f"{ref!r} matches more than one run; give more of the id", matches=sorted({Path(d).name for d in ids} | sessions)[:10])
    raise Refusal(f"no run or session {ref!r} in {runs_dir}")


def live_runs(runs_dir):
    """(run_dir, meta) of every live run, after reaping dead supervisors."""
    out = []
    for d, _ in iter_runs(runs_dir):
        meta = reap(d)
        if is_live(meta):
            out.append((d, meta))
    return out
