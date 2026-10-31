"""The registry in process: where it lives, claiming runs under a session's lock, compare-and-set outcomes, reaping, liveness by process group, the inbox and finding runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from support.harness import engine, git, make_repo

reg = engine("claude.registry")
Refusal = engine("claude.errors").Refusal


def sleeper():
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    return p


class Location(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_main_checkout_from_a_worktree(self):
        repo = make_repo(self.root / "repo")
        wt = self.root / "wt"
        git(repo, "worktree", "add", "-q", "-b", "x", str(wt))
        self.assertEqual(reg.resolve_runs_dir(str(wt)), str(repo / ".claude-runs"))
        self.assertEqual(reg.resolve_runs_dir(str(repo)), str(repo / ".claude-runs"))

    def test_outside_git_and_explicit(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(reg.resolve_runs_dir(str(plain)), str(plain / ".claude-runs"))
        self.assertEqual(reg.resolve_runs_dir(str(plain), str(self.root / "elsewhere")), str(self.root / "elsewhere"))

    def test_registry_ignores_itself(self):
        d = reg.ensure_runs_dir(str(self.root / "r" / ".claude-runs"))
        self.assertEqual((Path(d) / ".gitignore").read_text(), "*\n")


class Runs(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.runs = str(self.root / ".claude-runs")

    def publish(self, session="s1", label="t", state="starting", **meta):
        return reg.publish_run(self.runs, session, label, lambda existing: None, lambda rid, rdir: {"session_id": session, "state": state, "stdin_open": True, **meta})

    def test_publish_claims_a_directory_and_writes_meta(self):
        run_id, run_dir, meta = self.publish(label="My Label!")
        self.assertRegex(run_id, r"^\d{8}-\d{6}-my-label-[0-9a-f]{4}$")
        self.assertTrue((Path(run_dir) / "inbox").is_dir())
        self.assertEqual(reg.read_meta(run_dir)["run_id"], run_id)

    def test_check_sees_the_session_and_can_refuse(self):
        self.publish(session="s1")
        seen = []

        def check(existing):
            seen.extend(existing)
            raise Refusal("busy")

        with self.assertRaises(Refusal):
            reg.publish_run(self.runs, "s1", "t", check, lambda r, d: {"session_id": "s1"})
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(reg.iter_runs(self.runs)), 1)

    def test_first_outcome_wins(self):
        _, run_dir, _ = self.publish(supervisor_pid=os.getpid(), supervisor_pgid=os.getpgid(0))
        self.assertTrue(reg.record_if_active(run_dir, {"state": "completed"}))
        self.assertFalse(reg.record_if_active(run_dir, {"state": "orphaned"}))
        self.assertEqual(reg.read_meta(run_dir)["state"], "completed")

    def test_reap_dead_supervisor(self):
        p = subprocess.Popen(["true"], start_new_session=True)
        p.wait()
        _, run_dir, _ = self.publish(supervisor_pid=p.pid, supervisor_pgid=p.pid, state="running")
        reg.enqueue(run_dir, "uuid-1", "hello")
        meta = reg.reap(run_dir)
        self.assertEqual(meta["state"], "orphaned")
        self.assertEqual(meta["undelivered"], ["uuid-1"])

    def test_reap_leaves_a_live_supervisor_and_a_fresh_unsupervised_run(self):
        s = sleeper()
        self.addCleanup(s.kill)
        _, live, _ = self.publish(supervisor_pid=s.pid, supervisor_pgid=s.pid, state="running")
        self.assertEqual(reg.reap(live)["state"], "running")
        _, fresh, _ = self.publish(session="s2")
        self.assertEqual(reg.reap(fresh)["state"], "starting")
        _, stale, _ = self.publish(session="s3", created_at=time.time() - 3600)
        self.assertEqual(reg.reap(stale)["state"], "orphaned")

    def test_live_means_unfinished_or_claude_still_in_its_group(self):
        s = sleeper()
        self.addCleanup(s.kill)
        self.assertTrue(reg.is_live({"state": "running"}))
        self.assertFalse(reg.is_live({"state": "completed"}))
        self.assertTrue(reg.is_live({"state": "orphaned", "claude_pid": s.pid, "claude_pgid": s.pid}))
        self.assertFalse(reg.is_live({"state": "orphaned", "claude_pid": s.pid, "claude_pgid": s.pid + 99999}))

    def test_find_run(self):
        a, adir, _ = self.publish(session="aaaa-1111", label="one")
        time.sleep(0.01)
        b, bdir, _ = self.publish(session="aaaa-1111", label="two")
        c, cdir, _ = self.publish(session="bbbb-2222", label="three")
        self.assertEqual(reg.find_run(self.runs, a), adir)
        self.assertEqual(reg.find_run(self.runs, "aaaa-1111"), bdir)
        self.assertEqual(reg.find_run(self.runs, "bbbb"), cdir)
        self.assertEqual(reg.find_run(self.runs, "aaaa"), bdir)
        with self.assertRaises(Refusal) as e:
            reg.find_run(self.runs, a[:9])
        self.assertIn("more than one", e.exception.message)
        with self.assertRaises(Refusal):
            reg.find_run(self.runs, "zzzz")

    def test_unparsable_meta_is_named(self):
        _, run_dir, _ = self.publish()
        (Path(run_dir) / "meta.json").write_text("{nope")
        with self.assertRaises(Refusal) as e:
            reg.read_meta(run_dir)
        self.assertIn("does not parse", e.exception.message)


class Inbox(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _, self.run_dir, _ = reg.publish_run(str(self.root / "runs"), "s", "t", lambda e: None, lambda r, d: {"session_id": "s", "state": "running", "stdin_open": True})

    def test_queue_deliver_close(self):
        self.assertIsNone(reg.enqueue(self.run_dir, "u1", "first", kind="prompt"))
        self.assertIsNone(reg.enqueue(self.run_dir, "u2", "second", priority="now"))
        self.assertFalse(reg.close(self.run_dir, lambda meta: True), "closes with messages waiting")
        written = []
        delivered = reg.take(self.run_dir, written.append, lambda: 7)
        self.assertEqual([m["uuid"] for m in delivered], ["u1", "u2"])
        self.assertEqual([m["text"] for m in written], ["first", "second"])
        msgs = reg.read_meta(self.run_dir)["messages"]
        self.assertEqual([(m["uuid"], m["after_line"], m["kind"], m["priority"]) for m in msgs], [("u1", 7, "prompt", None), ("u2", 7, "send", "now")])
        self.assertFalse(reg.close(self.run_dir, lambda meta: False))
        self.assertTrue(reg.close(self.run_dir, lambda meta: True))
        self.assertEqual(reg.enqueue(self.run_dir, "u3", "late"), "closed")
        self.assertEqual(reg.take(self.run_dir, written.append, lambda: 0), [])

    def test_send_limit(self):
        for i in range(3):
            self.assertIsNone(reg.enqueue(self.run_dir, f"u{i}", "x", limit=3))
        self.assertEqual(reg.enqueue(self.run_dir, "u9", "x", limit=3), "limit")
        self.assertIsNone(reg.enqueue(self.run_dir, "p", "x", kind="prompt", limit=3), "the prompt is not a send")


if __name__ == "__main__":
    unittest.main()
