"""S5: the skill against the real `claude`, on the user's subscription and with the user's whole Claude Code environment. Skipped unless CLAUDE_SKILL_REAL=1; workers run on haiku to keep the cost down.

Run: CLAUDE_SKILL_REAL=1 python3 -m unittest tests/smoke_real_claude.py -v   (from the repository root)

Projects are created under <repo>/.tmp/, outside TMPDIR, because a sandboxed worker may write its TMPDIR and a project there would not show what the profile forbids. "Changes the worker's tools made" is measured against a baseline run in the same project and profile, since the user's SessionStart hooks and Claude Code itself create files at startup (`tree_snapshot` in tests/support/harness.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import unittest
import uuid
from pathlib import Path

from support.harness import ENTRY, REPO, git, make_repo, snapshot_diff, tree_snapshot

REAL = os.environ.get("CLAUDE_SKILL_REAL") == "1"
MODEL = os.environ.get("CLAUDE_SKILL_REAL_MODEL", "haiku")
BUGGY = {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "test_calc.py": "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
}


@unittest.skipUnless(REAL, "set CLAUDE_SKILL_REAL=1 to run against the real claude")
class Real(unittest.TestCase):
    def setUp(self):
        self.root = REPO / ".tmp" / f"smoke-{uuid.uuid4().hex[:8]}"
        self.root.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for meta in self.root.rglob("meta.json"):
            try:
                m = json.loads(meta.read_text())
                if m.get("claude_pgid") and m.get("state") not in ("completed", "failed", "interrupted", "timed_out", "orphaned"):
                    os.killpg(m["claude_pgid"], 9)
            except (OSError, ValueError):
                pass
        if os.environ.get("CLAUDE_SKILL_REAL_KEEP") != "1":
            shutil.rmtree(self.root, ignore_errors=True)

    def env(self):
        env = dict(os.environ)
        env.pop("CLAUDE_SKILL_TEST_TIMINGS", None)
        return env

    def cli(self, *args, cwd, timeout=600):
        proc = subprocess.run(["uv", "run", "--quiet", str(ENTRY), *args], cwd=cwd, capture_output=True, text=True, env=self.env(), timeout=timeout)
        return proc

    def cli_json(self, *args, cwd, expect=0, timeout=600):
        proc = self.cli(*args, cwd=cwd, timeout=timeout)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout.splitlines()[0])

    def run_to_end(self, prompt, *args, cwd):
        reply = self.cli_json("start", prompt, "--model", MODEL, "--effort", "low", *args, cwd=cwd)
        proc = self.cli("result", "--run", reply["run_id"], "--wait", "--wait-timeout", "500", cwd=cwd)
        header, _, text = proc.stdout.partition("\n")
        return reply, json.loads(header), text

    def baseline(self, project, profile):
        """Startup artifacts: what appears in `project` when a worker of `profile` only runs `true` once."""
        before = tree_snapshot(project)
        _, header, _ = self.run_to_end("Run the shell command `true` once with the Bash tool, then reply OK. Do nothing else.", "--profile", profile, cwd=project)
        self.assertEqual(header["state"], "completed", header)
        after = tree_snapshot(project)
        return after, snapshot_diff(before, after)

    def test_read_only_runs_tests_and_changes_nothing(self):
        project = make_repo(self.root / "ro", BUGGY)
        b, startup = self.baseline(project, "read-only")
        reply, header, text = self.run_to_end("Run `python3 -m unittest -q` in this directory and tell me which test fails and why. Do not change any file.", "--profile", "read-only", cwd=project)
        self.assertEqual(reply["permission_mode"], "dontAsk")
        self.assertEqual(header["state"], "completed", header)
        self.assertIn("test_add", text)
        log = self.cli("log", "--run", reply["run_id"], cwd=project).stdout
        self.assertRegex(log, r"bash exit=\d+ out=\d+B .*unittest")
        changed = snapshot_diff(b, tree_snapshot(project), allowed=startup)
        self.assertEqual(changed, [], f"the worker's tools changed the tree; startup artifacts were {startup}")
        print(f"\nread-only: startup artifacts {startup}; cost ${header['cost_usd']}")

    def test_resume_resends_the_profile(self):
        project = make_repo(self.root / "resume", BUGGY)
        first, header, _ = self.run_to_end("Reply with the single word ONE.", "--profile", "read-only", cwd=project)
        self.assertEqual(header["state"], "completed", header)
        again = self.cli_json("resume", first["run_id"], "Reply with the single word TWO.", cwd=project)
        self.assertEqual(again["permission_mode"], "dontAsk", "a resumed -p session falls back to the user's default mode unless the profile is sent again")
        proc = self.cli("result", "--run", again["run_id"], "--wait", "--wait-timeout", "300", cwd=project)
        self.assertIn("TWO", proc.stdout)
        changed = self.cli_json("resume", again["run_id"], "Reply with the single word THREE.", "--profile", "write", cwd=project)
        self.assertEqual((changed["permission_mode"], changed["profile_changed_from"]), ("acceptEdits", "read-only"))
        self.cli("result", "--run", changed["run_id"], "--wait", "--wait-timeout", "300", cwd=project)

    def test_send_redirects_a_running_worker(self):
        project = make_repo(self.root / "send", BUGGY)
        reply = self.cli_json("start", "Run `sleep 20` with the Bash tool in the foreground, then reply with the word RED.", "--model", MODEL, "--effort", "low", "--profile", "read-only", cwd=project)
        time.sleep(6)
        sent = self.cli_json("send", reply["run_id"], "Change of plan: when the command finishes, reply with the word BLUE instead of RED.", cwd=project)
        self.assertTrue(sent["delivered"], sent)
        proc = self.cli("result", "--run", reply["run_id"], "--wait", "--wait-timeout", "300", cwd=project)
        header, _, text = proc.stdout.partition("\n")
        header = json.loads(header)
        self.assertEqual(header["state"], "completed", header)
        self.assertIn("BLUE", text)
        self.assertIn(sent["message_uuid"], [a["uuid"] for a in header["answered"]])

    def test_stop_then_resume_knows_it_was_interrupted(self):
        project = make_repo(self.root / "stop", BUGGY)
        reply = self.cli_json("start", "Run `sleep 60` with the Bash tool in the foreground, then reply DONE.", "--model", MODEL, "--effort", "low", "--profile", "read-only", cwd=project)
        time.sleep(8)
        (entry,) = self.cli_json("stop", "--run", reply["run_id"], cwd=project)["stopped"]
        self.assertEqual(entry["state"], "interrupted")
        self.assertEqual(entry["signals_sent"][0], "SIGINT")
        again = self.cli_json("resume", reply["run_id"], "Was your previous command interrupted before it finished? Answer YES or NO and nothing else.", cwd=project)
        proc = self.cli("result", "--run", again["run_id"], "--wait", "--wait-timeout", "300", cwd=project)
        self.assertIn("YES", proc.stdout.upper().split("\n", 1)[1])


if __name__ == "__main__":
    unittest.main()
