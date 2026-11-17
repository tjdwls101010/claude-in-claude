"""The job side of the github unit: reading the job's environment, taking its handles from a worker (K9), and the workflow commands a step prints (K21; the runner's handling of them was observed on a real runner, plan stage 0 e)."""

from __future__ import annotations

import os
import tempfile
import unittest

from support.harness import engine

github = engine("claude.github")

JOB_ENV = {"GITHUB_RUN_ID": "44006368956", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "someone/project", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_STEP_SUMMARY": "/r/_temp/summary", "GITHUB_OUTPUT": "/r/_temp/out", "GITHUB_ENV": "/r/_temp/env", "GITHUB_PATH": "/r/_temp/path", "GITHUB_STATE": "/r/_temp/state", "GH_TOKEN": "t", "GITHUB_TOKEN": "t", "RUNNER_TRACKING_ID": "github_x", "HOME": "/h"}


class Job(unittest.TestCase):
    def test_context(self):
        ctx = github.job_context(JOB_ENV)
        self.assertEqual((ctx["job"], ctx["attempt"], ctx["event"]), ("44006368956-2", 2, "workflow_dispatch"))
        self.assertEqual(ctx["url"], "https://github.com/someone/project/actions/runs/44006368956/attempts/2")
        self.assertEqual(github.job_context({**JOB_ENV, "GITHUB_RUN_ATTEMPT": "1"})["url"], "https://github.com/someone/project/actions/runs/44006368956")
        self.assertIsNone(github.job_context({"HOME": "/h"}))

    def test_scrub_keeps_the_tracking_id(self):
        left = github.scrub_job_env(JOB_ENV)
        for k in ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY", "GH_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(k, left)
        self.assertEqual(left["RUNNER_TRACKING_ID"], "github_x")
        self.assertEqual(left["GITHUB_RUN_ID"], "44006368956")

    def test_annotation_escapes(self):
        self.assertEqual(github.annotation("error", "nightly: failed, again", "line1\nline2 100%"), "::error title=nightly%3A failed%2C again::line1%0Aline2 100%25")
        self.assertEqual(github.stop_commands("tok"), "::stop-commands::tok")
        self.assertEqual(github.resume_commands("tok"), "::tok::")

    def test_summary_and_output_files(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "s")
        github.write_summary(p, "# a")
        github.write_summary(p, "b\n")
        self.assertEqual(open(p).read(), "# a\nb\n")
        github.write_output(os.path.join(d, "o"), {"run_id": "r1", "state": "completed"})
        self.assertEqual(open(os.path.join(d, "o")).read(), "run_id=r1\nstate=completed\n")
        with self.assertRaises(OSError):
            github.write_summary(os.path.join(d, "missing", "s"), "x")


if __name__ == "__main__":
    unittest.main()
