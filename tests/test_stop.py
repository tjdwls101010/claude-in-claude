"""Stopping runs through their process groups: the signal ladder, what each stopped run records, and orphans whose supervisor is gone (J16)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from support.harness import ENTRY, FAST_TIMINGS, Sandbox


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Stop(Sandbox):
    def stop(self, *runs):
        args = []
        for r in runs:
            args += ["--run", r]
        return self.cli_json("stop", *args, timeout=60)["stopped"]

    def test_sigint_ends_a_running_turn(self):
        reply = self.start("x [[fake:sleep:30]]")
        (entry,) = self.stop(reply["run_id"])
        self.assertEqual(entry["signals_sent"], ["SIGINT"])
        self.assertEqual(entry["state"], "interrupted")
        self.assertEqual(entry["session_id"], reply["session_id"])
        self.assertEqual(self.status(reply["run_id"])["error"], "stopped")

    def test_ladder_escalates(self):
        reply = self.start("x [[fake:ignore_sigint]] [[fake:sleep:30]]")
        (entry,) = self.stop(reply["run_id"])
        self.assertEqual(entry["signals_sent"], ["SIGINT", "SIGTERM"])
        self.assertEqual(entry["state"], "interrupted")
        reply = self.start("x [[fake:ignore_sigint]] [[fake:ignore_sigterm]] [[fake:sleep:30]]")
        (entry,) = self.stop(reply["run_id"])
        self.assertEqual(entry["signals_sent"], ["SIGINT", "SIGTERM", "SIGKILL"])
        self.assertEqual(entry["state"], "interrupted")

    def test_ended_run_keeps_its_state(self):
        reply = self.start("x")
        self.wait_state(reply["run_id"])
        (entry,) = self.stop(reply["run_id"])
        self.assertEqual((entry["state"], entry["signals_sent"]), ("completed", []))
        self.assertIn("note", entry)

    def test_several_runs_at_once(self):
        a = self.start("a [[fake:sleep:30]]")
        b = self.start("b [[fake:sleep:30]]")
        entries = self.stop(a["run_id"], b["run_id"])
        self.assertEqual([e["state"] for e in entries], ["interrupted", "interrupted"])

    def test_unknown_run(self):
        reply = self.cli_json("stop", "--run", "nope", expect=1)
        self.assertIn("nope", reply["error"])
        self.cli_json("stop", expect=2)


class StopWhileStarting(Sandbox):
    """A stop that lands while a run is starting — after it is published, before its supervisor launches claude, or between the launch and the pid being recorded — keeps the worker from doing its work (K25). Each test pauses the start at one of those points (test timings) so the stop lands inside it every time."""

    PROMPT = "x [[fake:silent:1]] [[fake:write:worked.txt]]"

    def start_paused(self, pause):
        # FAKE_CLAUDE_STARTUP_LINK: the fake's SessionStart hook makes .claude/histories before it reads any message, as a real startup hook works before the prompt arrives.
        env = {**self.env, "FAKE_CLAUDE_STARTUP_LINK": "1", "CLAUDE_SKILL_TEST_TIMINGS": json.dumps({**FAST_TIMINGS, pause: 3})}
        proc = subprocess.Popen([sys.executable, str(ENTRY), "start", self.PROMPT], cwd=self.project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def meta(self):
        dirs = [d for d in self.runs_dir().glob("*") if (d / "meta.json").exists()] if self.runs_dir().exists() else []
        return json.loads((dirs[0] / "meta.json").read_text()) if dirs else None

    def launched(self):
        return [c for c in self.fake_calls() if "-p" in c["argv"]]

    def supervisor_child(self):
        """Whether the supervisor has launched a process (the start of claude) while no pid is recorded yet."""
        m = self.meta()
        if not m or not m.get("supervisor_pid") or m.get("claude_pid"):
            return False
        return bool(subprocess.run(["pgrep", "-P", str(m["supervisor_pid"])], capture_output=True, text=True).stdout.strip())

    def assert_nothing_ran(self, meta):
        self.assertEqual(self.launched(), [], "claude ran for a run stopped before its pid was recorded")
        self.assertFalse((self.project / ".claude" / "histories").is_symlink(), "claude's startup ran after the stop")
        self.assertFalse((self.project / "worked.txt").exists())
        self.assertEqual(self.status(meta["run_id"])["undelivered"], [m["uuid"] for m in meta["messages"]], "the prompt that was never delivered is not reported")

    def stop_and_settle(self, proc):
        meta = self.meta()
        (entry,) = self.cli_json("stop", "--run", meta["run_id"], timeout=60)["stopped"]
        proc.communicate(timeout=60)

        def settled():
            m = self.meta()
            return m if not any(pid and pid_alive(pid) for pid in (m.get("supervisor_pid"), m.get("claude_pid"))) else None

        meta = self.wait_for(settled, timeout=30, what="the supervisor and claude to exit")
        return entry, meta

    def test_stop_after_publish(self):
        proc = self.start_paused("pause_after_publish")
        self.wait_for(lambda: (m := self.meta()) and not m.get("supervisor_pid"), what="the published run")
        entry, meta = self.stop_and_settle(proc)
        self.assertEqual((entry["state"], meta["state"], meta["error"]), ("interrupted", "interrupted", "stopped"))
        self.assert_nothing_ran(meta)

    def test_stop_before_launch(self):
        proc = self.start_paused("pause_before_launch")
        self.wait_for(lambda: (m := self.meta()) and (self.run_dir(m["run_id"]) / "stderr.log").exists(), what="the supervisor to reach the launch")
        self.assertEqual(self.launched(), [])
        entry, meta = self.stop_and_settle(proc)
        self.assertEqual((entry["state"], meta["state"], meta["error"]), ("interrupted", "interrupted", "stopped"))
        self.assert_nothing_ran(meta)

    def test_stop_that_outwaits_a_slow_supervisor(self):
        # stop waits a few seconds for the supervisor, then records the outcome itself: that record must name the undelivered prompt too.
        env = {**self.env, "CLAUDE_SKILL_TEST_TIMINGS": json.dumps({**FAST_TIMINGS, "pause_before_launch": 10})}
        proc = subprocess.Popen([sys.executable, str(ENTRY), "start", self.PROMPT], cwd=self.project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.wait_for(lambda: (m := self.meta()) and (self.run_dir(m["run_id"]) / "stderr.log").exists(), what="the supervisor to reach the launch")
        entry, meta = self.stop_and_settle(proc)
        self.assertEqual((entry["state"], meta["state"]), ("interrupted", "interrupted"))
        self.assert_nothing_ran(meta)

    def test_stop_before_pid_is_recorded(self):
        proc = self.start_paused("pause_before_pid")
        self.wait_for(self.supervisor_child, what="claude's process to be started")
        entry, meta = self.stop_and_settle(proc)
        self.assertEqual((entry["state"], meta["state"], meta["error"]), ("interrupted", "interrupted", "stopped"))
        self.assert_nothing_ran(meta)

    def test_stop_that_read_the_run_before_the_pid_was_recorded(self):
        # stop reads the run while the pid is unrecorded, the supervisor records it and finds no request yet, then stop marks the run: stop must signal the pid it now finds.
        self.PROMPT = "x [[fake:silent:6]] [[fake:write:worked.txt]]"
        proc = self.start_paused("pause_before_pid")
        self.wait_for(self.supervisor_child, what="claude's process to be started")
        meta = self.meta()
        stopper = subprocess.Popen([sys.executable, str(ENTRY), "stop", "--run", meta["run_id"]], cwd=self.project, env={**self.env, "CLAUDE_SKILL_TEST_TIMINGS": json.dumps({**FAST_TIMINGS, "pause_before_stop_mark": 5})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = stopper.communicate(timeout=60)
        (entry,) = json.loads(out)["stopped"]
        proc.communicate(timeout=60)
        self.assertEqual(entry["signals_sent"][:1], ["SIGINT"])
        meta = self.wait_for(lambda: (m := self.meta()) and not pid_alive(m["supervisor_pid"]) and m, timeout=30, what="the supervisor to exit")
        self.assertEqual(meta["state"], "interrupted")
        self.assertFalse((self.project / "worked.txt").exists(), "the worker did its work after the stop")


class Orphans(Sandbox):
    def kill_supervisor(self, run_id):
        meta = json.loads((self.run_dir(run_id) / "meta.json").read_text())
        os.kill(meta["supervisor_pid"], signal.SIGKILL)
        return meta

    def test_dead_supervisor_is_reaped_and_claude_still_writing_is_live(self):
        reply = self.start("x [[fake:sleep:30]]")
        # Kill the supervisor while the Bash call runs: the worker writes nothing then, so its stdout pipe closing does not end it.
        self.wait_for(lambda: self.status(reply["run_id"])["in_progress"], what="the Bash call to start")
        self.kill_supervisor(reply["run_id"])
        row = self.wait_state(reply["run_id"], states=("orphaned",))
        self.assertTrue(row["still_writing"])
        self.assertIn("supervisor", row["error"])
        listing = self.cli_json("status")
        self.assertIn(reply["run_id"], listing["live"])
        (entry,) = self.cli_json("stop", "--run", reply["run_id"])["stopped"]
        self.assertEqual(entry["signals_sent"], ["SIGINT"])
        self.assertEqual(entry["state"], "orphaned")
        self.assertNotIn("still_writing", self.status(reply["run_id"]))


class ForgedMeta(Sandbox):
    def test_stop_signals_only_a_claude_process(self):
        import subprocess

        reply = self.start("x")
        self.wait_state(reply["run_id"])
        victim = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(victim.kill)
        path = self.run_dir(reply["run_id"]) / "meta.json"
        meta = json.loads(path.read_text())
        meta.update({"claude_pid": victim.pid, "claude_pgid": victim.pid, "state": "orphaned"})
        path.write_text(json.dumps(meta))
        (entry,) = self.cli_json("stop", "--run", reply["run_id"])["stopped"]
        self.assertEqual(entry["signals_sent"], [])
        self.assertIn("not claude", entry["note"])
        self.assertIsNone(victim.poll(), "the forged process group was signalled")
