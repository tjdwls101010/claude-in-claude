"""Races between real processes: two creators on one session, and a supervisor killed mid-run."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

from support.harness import SCRIPTS

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
