"""Races between real processes: two creators on one session, and a supervisor killed mid-run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import unittest
from pathlib import Path

from support.harness import SCRIPTS, Sandbox

CLAIM = r"""
import json, sys, time
from claude.registry import publish_run, is_live
from claude.errors import Refusal
runs, start = sys.argv[1], float(sys.argv[2])
while time.time() < start:
    time.sleep(0.001)
def check(existing):
    if any(is_live(m) for m in existing):
        raise Refusal("busy")
    time.sleep(0.2)  # widen the window between check and claim
try:
    rid, _, _ = publish_run(runs, "same-session", "race", check, lambda r, d: {"session_id": "same-session", "state": "starting", "supervisor_pid": __import__("os").getpid()})
    print(json.dumps({"claimed": rid}))
except Refusal as e:
    print(json.dumps({"refused": e.message}))
"""


class SessionLock(unittest.TestCase):
    def test_one_of_two_concurrent_creators_wins(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        import time

        at = time.time() + 0.5
        env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
        procs = [subprocess.Popen([sys.executable, "-c", CLAIM, str(root / "runs"), str(at)], stdout=subprocess.PIPE, text=True, env=env) for _ in range(2)]
        outs = [json.loads(p.communicate(timeout=30)[0]) for p in procs]
        self.assertEqual(sorted(k for o in outs for k in o), ["claimed", "refused"])



class CliRaces(Sandbox):
    def test_two_resumes_of_one_session_at_once(self):
        import threading

        first = self.start("x")
        self.wait_state(first["run_id"])
        out = []

        def go():
            out.append(self.cli("resume", first["session_id"], "again [[fake:sleep:2]]"))

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        codes = sorted(p.returncode for p in out)
        self.assertEqual(codes, [0, 1], [p.stdout for p in out])
        refused = json.loads(next(p for p in out if p.returncode == 1).stdout)
        self.assertIn("live run", refused["error"])
        for p in out:
            if p.returncode == 0:
                self.wait_state(json.loads(p.stdout)["run_id"])

    def test_sends_racing_the_close_are_delivered_or_refused(self):
        """A send either lands in the run (and is delivered) or is refused; none is accepted and then lost. A burst of sends around the answer races the close; a second burst after the run has ended must all be refused."""
        import threading

        for attempt in range(3):
            reply = self.start(f"quick {attempt} [[fake:silent:0.7]] [[fake:reply:done]]")
            results = []

            def go(i):
                time.sleep(0.1 * i)
                results.append(self.cli("send", reply["run_id"], f"late {i}"))

            burst = [threading.Thread(target=go, args=(i,)) for i in range(8)]
            for t in burst:
                t.start()
            for t in burst:
                t.join()
            row = self.wait_state(reply["run_id"], timeout=60)
            after = [self.cli("send", reply["run_id"], "after the end") for _ in range(2)]
            self.assertEqual([p.returncode for p in after], [1, 1])
            accepted = [json.loads(p.stdout) for p in results if p.returncode == 0]
            refused = [json.loads(p.stdout) for p in results if p.returncode == 1]
            self.assertEqual(len(accepted) + len(refused), 8)
            self.assertTrue(all(a["delivered"] for a in accepted), accepted)
            self.assertEqual(row["undelivered"], [])
            self.assertEqual(row["messages"], 1 + len(accepted))
            (call,) = [c for c in self.fake_calls() if "-p" in c["argv"] and c["env"].get("CLAUDE_SKILL_RUN") == reply["run_id"]]
            self.assertEqual(sorted(m["uuid"] for m in call["messages"][1:]), sorted(a["message_uuid"] for a in accepted))

    def test_two_batches_with_one_name(self):
        import threading

        out = []

        def go(i):
            out.append(self.cli("batch", "--group", "same", "--task", f"t{i}", timeout=120))

        threads = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(p.returncode for p in out), [0, 1], [p.stdout for p in out])
        self.assertIn("reserved", json.loads(next(p for p in out if p.returncode == 1).stdout)["error"])
        self.assertEqual(self.cli_json("status", "--group", "same")["group_state"] in ("running", "completed"), True)
