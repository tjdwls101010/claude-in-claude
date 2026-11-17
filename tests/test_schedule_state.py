"""The schedule state store (K4·K19): which automatic trigger fills a slot, the one retry a failed read-only slot gets, the hand-over from a job's Run step to its Finish step, and rebuilding all of it from the runs when the state file is lost. The cases are the plan's K4 walk-through."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support.harness import engine

registry = engine("claude.registry")

S3, S4 = 1794852000, 1794855600  # 03:00 and 04:00 KST, 2026-11-17


class Claims(unittest.TestCase):
    def setUp(self):
        self.reg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.reg, ignore_errors=True)

    def entry(self, profile="read-only", trigger="dispatcher"):
        return {"trigger": trigger, "mode": "run", "profile": profile}

    def run_for(self, job, slot, state, retry_of=None, live=False):
        """A run of this schedule as `__scheduled run` publishes it, ended in `state`."""
        origin = {"kind": "schedule", "name": "nightly", "trigger": "dispatcher", "slot": slot, "job": job, "url": f"https://example.invalid/runs/{job}"}
        if retry_of:
            origin["retry_of"] = retry_of
        meta = {"state": state, "settings": {"profile": "read-only"}, "origin": origin}
        if live:
            meta["supervisor_pid"] = os.getpid()
        registry.publish_run(self.reg, f"s-{job}", "nightly", lambda existing: None, lambda rid, d: meta)

    def claim(self, slot, job, **kw):
        return registry.claim_slot(self.reg, "nightly", slot, job, self.entry(**kw))

    def test_first_trigger_fills_the_slot_and_a_late_one_is_skipped(self):
        # ① the 03:00 dispatcher runs; the backup arriving at 05:47 computes the same slot and skips
        self.assertEqual(self.claim(S3, "1-1")["decision"], "first")
        self.run_for("1-1", S3, "completed")
        late = self.claim(S3, "2-1")
        self.assertEqual(late["decision"], "skip")
        self.assertEqual(late["previous"]["job"], "1-1")
        self.assertEqual(late["previous"]["url"], "https://example.invalid/runs/1-1")
        self.assertEqual(registry.read_job(self.reg, "nightly", "2-1")["outcome"]["kind"], "skipped")

    def test_an_older_slot_after_a_newer_one_is_skipped(self):
        # ② an hourly backup 70 minutes late: the 04:00 slot already ran, so the 03:00 trigger finds nothing to fill
        self.claim(S4, "1-1")
        self.assertEqual(self.claim(S3, "2-1")["decision"], "skip")

    def test_triggers_queued_while_asleep_run_once(self):
        # ③ three slots missed: the wake-up dispatcher fills the newest, the queued backups skip
        self.assertEqual(self.claim(S4, "9-1")["decision"], "first")
        self.assertEqual([self.claim(S4, f"{n}-1")["decision"] for n in (6, 7, 8)], ["skip"] * 3)

    def test_a_backup_fills_a_slot_the_dispatcher_missed(self):
        # ④ the dispatcher's gh call failed: the backup is the first trigger for the slot
        self.assertEqual(self.claim(S3, "2-1", trigger="schedule")["decision"], "first")

    def test_a_failed_read_only_slot_is_retried_once(self):
        self.claim(S3, "1-1")
        self.run_for("1-1", S3, "failed")
        again = self.claim(S3, "2-1")
        self.assertEqual(again["decision"], "retry")
        self.assertEqual(again["previous"]["job"], "1-1")
        self.assertEqual(registry.read_job(self.reg, "nightly", "2-1")["retry_of"], "1-1")
        self.run_for("2-1", S3, "failed", retry_of="1-1")
        self.assertEqual(self.claim(S3, "3-1")["decision"], "skip")

    def test_no_retry_for_writers_stopped_runs_or_live_runs(self):
        for state, profile, live in (("failed", "write", False), ("interrupted", "read-only", False), ("completed", "read-only", False), ("running", "read-only", True)):
            with self.subTest(state=state, profile=profile):
                self.setUp()
                self.claim(S3, "1-1", profile=profile)
                self.run_for("1-1", S3, state, live=live)
                self.assertEqual(self.claim(S3, "2-1", profile=profile)["decision"], "skip")

    def test_a_refusal_before_the_worker_counts_as_not_completed(self):
        # K28 ④: the slot was taken, then the start was refused: read-only retries once, a writer does not
        self.claim(S3, "1-1")
        registry.update_job(self.reg, "nightly", "1-1", {"outcome": {"kind": "refused", "error": "no commit"}})
        self.assertEqual(self.claim(S3, "2-1")["decision"], "retry")
        self.setUp()
        self.claim(S3, "1-1", profile="write")
        registry.update_job(self.reg, "nightly", "1-1", {"outcome": {"kind": "refused", "error": "no commit"}})
        self.assertEqual(self.claim(S3, "2-1", profile="write")["decision"], "skip")

    def test_the_retry_follows_the_profile_of_the_job_that_failed(self):
        # The schedule went from write to read-only between the two triggers: the writer's half-done slot is not tried again.
        self.claim(S3, "1-1", profile="write")
        registry.update_job(self.reg, "nightly", "1-1", {"outcome": {"kind": "refused", "error": "below the version floor"}})
        self.assertEqual(self.claim(S3, "2-1", profile="read-only")["decision"], "skip")

    def test_a_lost_state_file_is_rebuilt_from_the_runs(self):
        self.claim(S3, "1-1")
        self.run_for("1-1", S3, "failed")
        self.claim(S3, "2-1")
        self.run_for("2-1", S3, "failed", retry_of="1-1")
        shutil.rmtree(Path(registry.schedule_dir(self.reg, "nightly")))
        self.assertIsNone(registry.schedule_state(self.reg, "nightly"))
        self.assertEqual(self.claim(S3, "3-1")["decision"], "skip", "the slot's retry is known from the retry run's origin")
        self.assertEqual(registry.schedule_state(self.reg, "nightly")["last_slot"], S3)

    def test_manual_jobs_are_recorded_without_a_slot(self):
        self.claim(S3, "1-1")
        registry.record_job(self.reg, "nightly", "5-1", {"trigger": "manual", "mode": "run", "profile": "read-only"})
        self.assertEqual(registry.schedule_state(self.reg, "nightly")["last_slot"], S3)
        self.assertEqual(registry.read_job(self.reg, "nightly", "5-1")["trigger"], "manual")
        self.assertIsNone(registry.read_job(self.reg, "nightly", "6-1"))

    def test_runs_are_found_by_their_job(self):
        self.run_for("1-1", S3, "completed")
        self.run_for("2-1", S4, "completed")
        found = registry.find_by_origin_job(self.reg, "2-1")
        self.assertEqual(len(found), 1)
        self.assertEqual(registry.read_meta(found[0])["origin"]["slot"], S4)
        self.assertEqual(registry.find_by_origin_job(self.reg, "3-1"), [])


if __name__ == "__main__":
    unittest.main()
