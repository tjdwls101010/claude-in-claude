"""The detached supervisor: it starts one `claude -p` process for a run, copies its stdout to events.jsonl while reading it, writes queued messages to its stdin, closes stdin once every message has been answered, enforces the run's deadline, and records the outcome.

When stdin closes (J1): (a) every delivered message's uuid appears in some result, or (b) the last result seen is not a background follow-up, came after the last delivered message, no hook is still running, and stdout has been silent for the idle grace — which covers a message a hook dropped, whose uuid no result will ever carry. Both are decided under the run's lock with the inbox empty, so a message `send` queued is delivered first.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from claude.claude_cli import PROFILES, StreamState, encode_user_message, final_result, read_events, worker_env
from claude.git import startup_snapshot
from claude.registry import TERMINAL, close, pending, read_meta, record_if_active, take, update_meta
from claude.util import now, pid_alive, timings

EXPECTED_MODE = {"read-only": "dontAsk", "write": "acceptEdits", "auto": "auto"}
STDERR_TAIL = 2000


def log(run_dir, text):
    with open(Path(run_dir) / "supervisor.log", "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def signal_ladder(pgid, pid, *, grace=None, kill_grace=None, on_signal=None):
    """Interrupt a process group: SIGINT, then SIGTERM after `grace`, then SIGKILL after `kill_grace`, stopping as soon as `pid` is gone. SIGINT first lets Claude Code end the turn and keep the session resumable. Returns the signals sent."""
    t = timings()
    grace = t["stop_grace"] if grace is None else grace
    kill_grace = t["kill_grace"] if kill_grace is None else kill_grace
    sent = []
    for sig, wait in ((signal.SIGINT, grace), (signal.SIGTERM, kill_grace), (signal.SIGKILL, 0)):
        if not pid_alive(pid, pgid):
            break
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            break
        sent.append(sig.name)
        if on_signal:
            on_signal(sig.name)
        end = time.time() + wait
        while time.time() < end and pid_alive(pid, pgid):
            time.sleep(0.05)
    return sent


class Pump:
    """Reads claude's stdout line by line: appends each raw line to events.jsonl and feeds it to a StreamState."""

    def __init__(self, proc, events_path, on_first_init=None):
        self.proc = proc
        self.on_first_init = on_first_init
        self.first_init_result = None
        self.init_done = threading.Event()  # set once the first init has been read and its callback has run
        self.state = StreamState()
        self.lock = threading.Lock()
        self.lines = 0
        self.last_line_at = now()
        self.events_path = events_path
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        with open(self.events_path, "ab") as out:
            for raw in iter(self.proc.stdout.readline, b""):
                out.write(raw if raw.endswith(b"\n") else raw + b"\n")
                out.flush()
                try:
                    e = json.loads(raw)
                except ValueError:
                    e = None
                with self.lock:
                    self.lines += 1
                    self.last_line_at = now()
                    first = isinstance(e, dict) and e.get("type") == "system" and e.get("subtype") == "init" and self.state.init is None
                    if isinstance(e, dict):
                        self.state.feed(e)
                    else:
                        self.state.unparsed += 1
                if first:
                    if self.on_first_init:
                        # Right here, not on the next poll: the worker's first tool call is already on its way.
                        self.first_init_result = self.on_first_init(self.state.init)
                    self.init_done.set()


def should_close(meta, pump, grace):
    """J1, read under the pump's lock: (a) every delivered uuid answered, or (b) the last answer followed the last delivery and stdout has been quiet for `grace` with no hook running."""
    delivered = [m for m in meta.get("messages") or [] if m.get("after_line") is not None]
    if not delivered:
        return False
    with pump.lock:
        results = list(pump.state.results)
        answered = set()
        for r in results:
            answered |= set(r["uuids"] or [])
        quiet = now() - pump.last_line_at
        hooks_open = len(pump.state.hooks_open)
    if all(m.get("uuid") in answered for m in delivered):
        return "answered"
    if not results:
        return False
    last = results[-1]
    if last["origin"] == "task-notification":
        return False
    if last["index"] < delivered[-1]["after_line"]:
        return False
    if quiet >= grace and hooks_open == 0:
        return "idle"
    return False


def outcome(meta, run_dir, returncode):
    """The state, error and answer fields recorded when the process has exited."""
    events, unparsed = read_events(Path(run_dir) / "events.jsonl")
    messages = meta.get("messages") or []
    final = final_result(events, messages)
    fields = {
        "exit_code": returncode,
        "ended_at": now(),
        "unanswered": [m["uuid"] for m in final["unanswered"]],
        "undelivered": [m["uuid"] for m in messages if m.get("after_line") is None],
        "unparsed_events": unparsed,
    }
    stderr_tail = ""
    try:
        data = (Path(run_dir) / "stderr.log").read_bytes()
        stderr_tail = data[-STDERR_TAIL:].decode("utf-8", "ignore").strip()
    except OSError:
        pass
    result = final["result"]
    if meta.get("stop_requested"):
        state, error = "interrupted", "stopped"
    elif meta.get("timed_out_at"):
        state, error = "timed_out", f"--timeout of {meta['settings'].get('timeout')} s passed"
    elif meta.get("cwd_mismatch"):
        state, error = "failed", meta["cwd_mismatch"]
    elif returncode != 0:
        state = "failed"
        error = final["error"] or (f"claude exited {returncode}" + (f": {stderr_tail.splitlines()[-1][:300]}" if stderr_tail else ""))
    elif final["error"]:
        state, error = "failed", final["error"]
    elif result is None:
        state, error = "failed", "claude exited without a result"
    elif result["is_error"] or result["subtype"] != "success":
        state = "failed"
        parts = [result["subtype"]]
        if result["terminal_reason"]:
            parts.append(f"terminal_reason={result['terminal_reason']}")
        if result["api_error_status"]:
            parts.append(f"api_error_status={result['api_error_status']}")
        if result["errors"]:
            parts.append("; ".join(str(e) for e in result["errors"])[:300])
        elif result["text"]:
            parts.append(result["text"][:300])
        error = " ".join(parts)
    else:
        state, error = "completed", None
    fields.update({"state": state, "error": error})
    if state == "failed" and stderr_tail:
        fields["stderr_tail"] = stderr_tail[-600:]
    return fields


def supervise(run_dir):
    """Run one claude process for the run in `run_dir` to its end. Exits when the process has and the outcome is recorded."""
    t = timings()
    run_dir = str(run_dir)
    meta = read_meta(run_dir)
    update_meta(run_dir, lambda m: m.update({"supervisor_pid": os.getpid(), "supervisor_pgid": os.getpgid(0)}))
    env = worker_env(dict(os.environ), meta["run_id"])
    stderr_file = open(Path(run_dir) / "stderr.log", "ab")
    try:
        proc = subprocess.Popen(meta["argv"], cwd=meta["launch_cwd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_file, env=env, start_new_session=True)
    except OSError as e:
        record_if_active(run_dir, {"state": "failed", "error": f"could not start claude: {e}", "ended_at": now(), "stdin_open": False})
        return 1
    update_meta(run_dir, lambda m: m.update({"claude_pid": proc.pid, "claude_pgid": proc.pid, "started_at": now()}))
    log(run_dir, f"claude pid {proc.pid}: {' '.join(meta['argv'][:3])} …")
    wt = meta.get("worktree")

    def snapshot(init):
        if wt and meta.get("kind") == "start" and init.get("cwd"):
            try:
                return startup_snapshot(init["cwd"], wt.get("repo") or meta["launch_cwd"])
            except OSError as e:
                log(run_dir, f"startup snapshot failed: {e}")
        return None

    pump = Pump(proc, Path(run_dir) / "events.jsonl", on_first_init=snapshot)
    profile = meta["settings"]["profile"]
    seen_init = False
    rate_limit = None
    retrying = False
    finishing = False
    deadline = (now() + float(meta["settings"]["timeout"])) if meta["settings"].get("timeout") else None
    stdin_open = True

    def deliver(msg):
        proc.stdin.write(encode_user_message(msg["text"], msg["uuid"], msg.get("priority")).encode("utf-8"))
        proc.stdin.flush()

    def lines_read():
        with pump.lock:
            return pump.lines

    while proc.poll() is None:
        if stdin_open:
            try:
                for m in take(run_dir, deliver, lines_read):
                    log(run_dir, f"delivered {m['kind']} {m['uuid']} priority={m.get('priority')}")
            except (BrokenPipeError, OSError) as e:
                log(run_dir, f"stdin write failed: {e}")
        with pump.lock:
            init = pump.state.init if pump.init_done.is_set() else None
            rl = pump.state.rate_limit
            last_retry = pump.state.last_event_is_retry
        changes = {}
        if init and not seen_init:
            seen_init = True
            changes.update({"init": init, "state": "running", "mode_mismatch": init["permission_mode"] != EXPECTED_MODE.get(profile)})
            if wt and meta.get("kind") == "start" and init.get("cwd"):
                # The worktree's startup artifacts, taken once, at the first init of the run that created it: SessionStart hooks have run and no tool call has yet (J9).
                changes["startup_artifacts"] = pump.first_init_result or {}
                changes["cwd"] = init["cwd"]
                changes["worktree"] = {**wt, "path": init["cwd"]}
            expect = meta.get("expect_cwd")
            if expect and init.get("cwd") and os.path.realpath(init["cwd"]) != os.path.realpath(expect):
                changes["cwd_mismatch"] = f"cwd_mismatch: claude started in {init['cwd']}, not the recorded worktree {expect}; SessionStart hooks and the first tool call may already have run in the launch directory"
        if rl is not None and rl != rate_limit:
            rate_limit = rl
            changes["rate_limit"] = {**rl, "observed_at": now()}
        if last_retry and not retrying:
            retrying = True
            changes["retrying_since"] = now()
        elif not last_retry and retrying:
            retrying = False
            changes["retrying_since"] = None
        if changes:
            update_meta(run_dir, lambda m: m.update(changes))
            if changes.get("cwd_mismatch"):
                log(run_dir, changes["cwd_mismatch"])
                signal_ladder(proc.pid, proc.pid)
        if stdin_open:
            def decide(m):
                return should_close(m, pump, t["idle_grace"])

            if close(run_dir, decide):
                stdin_open = False
                log(run_dir, "stdin closed")
                try:
                    proc.stdin.close()
                except OSError:
                    pass
        elif not finishing and proc.poll() is None:
            # stdin is closed but the process lives on: whatever it still runs (an MCP task) is shown as finishing.
            time.sleep(t["poll"])
            if proc.poll() is None:
                finishing = True
                update_meta(run_dir, lambda m: m.update({"state": "finishing", "finishing_since": now()}) if m.get("state") not in TERMINAL else None)
        if deadline and now() >= deadline:
            log(run_dir, "deadline passed")
            update_meta(run_dir, lambda m: m.update({"timed_out_at": now()}))
            signal_ladder(proc.pid, proc.pid)
            deadline = None
        time.sleep(t["poll"])
    pump.thread.join(timeout=10)
    returncode = proc.returncode
    log(run_dir, f"claude exited {returncode}")
    stderr_file.close()

    with pump.lock:
        init = pump.state.init

    def finish(m):
        if m.get("state") in TERMINAL:
            return
        if init and not m.get("init"):
            # The process can end between two polls; its init is still part of what the run reported.
            m.update({"init": init, "mode_mismatch": init["permission_mode"] != EXPECTED_MODE.get(profile)})
        m.update(outcome(m, run_dir, returncode))
        m["stdin_open"] = False

    update_meta(run_dir, finish)
    return 0


def main(run_dir):
    try:
        return supervise(run_dir)
    except Exception as e:  # The outcome must be recorded even when the supervisor itself breaks.
        import traceback

        log(run_dir, "supervisor error:\n" + traceback.format_exc())
        try:
            record_if_active(run_dir, {"state": "failed", "error": f"supervisor error: {e}", "ended_at": now(), "stdin_open": False})
        except Exception:
            pass
        return 1
