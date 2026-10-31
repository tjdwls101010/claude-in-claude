"""Stopping runs through their process groups: the signal ladder, what each stopped run records, and orphans whose supervisor is gone (J16)."""

from __future__ import annotations

import json
import os
import signal
import time

from support.harness import Sandbox


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
