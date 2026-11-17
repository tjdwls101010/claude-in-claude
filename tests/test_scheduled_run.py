"""A scheduled job's two steps through the CLI (`__scheduled run` and `__scheduled finish`), in a job environment like the runner's, with the fake claude: each row of the plan's "ends and exit codes" table, the slot rules (K4), the hand-over between the steps (K19), the job's handles kept from the worker (K9), worktree runs (K10), the changes a run made (K27) and the workflow commands a worker cannot issue (K21). Summaries are checked for their sections, not their text, since a fake run's ids and times differ every time; their text is test_summary's."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from support.harness import ENTRY, FAST_TIMINGS, Sandbox, git

SLOT = 1794852000  # 2026-11-17 03:00 KST
LATER = SLOT + 2 * 3600 + 47 * 60  # 05:47 the same day


class Job(Sandbox):
    profile = "read-only"

    def job_env(self, run_id="44006368956", attempt=1, event="workflow_dispatch", source="", mode="run", prompt="look around", schema=None, now=LATER, extra=None):
        d = self.root / "job" / f"{run_id}-{attempt}"
        d.mkdir(parents=True, exist_ok=True)
        for name in ("summary", "output", "env", "path", "state"):
            (d / name).touch()
        env = {"GITHUB_RUN_ID": str(run_id), "GITHUB_RUN_ATTEMPT": str(attempt), "GITHUB_EVENT_NAME": event, "GITHUB_REPOSITORY": "someone/project", "GITHUB_SERVER_URL": "https://github.com", "GITHUB_STEP_SUMMARY": str(d / "summary"), "GITHUB_OUTPUT": str(d / "output"), "GITHUB_ENV": str(d / "env"), "GITHUB_PATH": str(d / "path"), "GITHUB_STATE": str(d / "state"), "GH_TOKEN": "job-token", "GITHUB_TOKEN": "job-token", "RUNNER_TRACKING_ID": "github_tracking", "CLAUDE_SCHEDULE_MODE": mode, "CLAUDE_SCHEDULE_SOURCE": source, "CLAUDE_SCHEDULE_PROMPT": prompt, "CLAUDE_SKILL_TEST_NOW": str(now)}
        if schema:
            env["CLAUDE_SCHEDULE_SCHEMA"] = schema
        env.update(extra or {})
        return env

    def args(self, step, profile=None, cron="0 3 * * *", at=None, worktree=False, timeout=600, project=None):
        a = ["__scheduled", step, "--name", "nightly", "--project", str(project or self.project), "--profile", profile or self.profile, "--model", "haiku", "--effort", "low", "--timeout", str(timeout), "--timezone", "Asia/Seoul"]
        a += ["--at", at] if at else ["--cron", cron]
        return a + (["--worktree"] if worktree else [])

    def step(self, step, env, **kw):
        return self.cli(*self.args(step, **kw), env=env, timeout=120)

    def job(self, env, **kw):
        """Run then Finish, as the runner does; returns both processes and the posted summary."""
        run = self.step("run", env, **kw)
        finish = self.step("finish", env, **kw)
        return run, finish, Path(env["GITHUB_STEP_SUMMARY"]).read_text()

    def worker_calls(self):
        return [c for c in self.fake_calls() if "-p" in c["argv"]]

    def scheduled_runs(self):
        out = []
        for meta in sorted(self.runs_dir().glob("*/meta.json")):
            m = json.loads(meta.read_text())
            if (m.get("origin") or {}).get("kind") == "schedule":
                out.append(m)
        return sorted(out, key=lambda m: m["created_at"])

    def output(self, env):
        return dict(l.split("=", 1) for l in Path(env["GITHUB_OUTPUT"]).read_text().splitlines() if "=" in l)


class Ends(Job):
    """The plan's table of ends and exit codes, one test per row."""

    def test_completed(self):
        env = self.job_env(prompt="review the code [[fake:reply:all good]]")
        run, finish, summary = self.job(env)
        self.assertEqual((run.returncode, finish.returncode), (0, 0), run.stdout + finish.stdout)
        self.assertTrue(summary.startswith("# ✅ nightly · completed\n"), summary[:200])
        self.assertIn("all good", summary)
        (meta,) = self.scheduled_runs()
        self.assertEqual(self.output(env), {"run_id": meta["run_id"], "state": "completed"})
        self.assertEqual((self.run_dir(meta["run_id"]) / "summary.md").read_text(), summary, "the same text is kept beside the run")
        self.assertIn(f"run={meta['run_id']} state=completed", run.stdout)

    def test_completed_with_a_denial_is_green_with_a_warning(self):
        self.profile = "write"
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:deny:/etc/nope.txt]]"))
        self.assertEqual((run.returncode, finish.returncode), (0, 0))
        self.assertIn("[!WARNING]", summary)
        self.assertIn("`/etc/nope.txt`", summary)

    def test_a_failure_is_red_with_its_error(self):
        env = self.job_env(prompt="x [[fake:auth_fail]]")
        run, finish, summary = self.job(env)
        self.assertEqual((run.returncode, finish.returncode), (1, 0))
        self.assertTrue(summary.startswith("# ❌ nightly · failed\n"), summary[:200])
        self.assertIn("Invalid API key", summary.split("[!CAUTION]", 1)[1])
        self.assertIn("::error title=nightly failed::", finish.stdout)
        self.assertEqual(self.output(env)["state"], "failed")

    def test_a_schema_run_without_structured_output_is_red(self):
        schema = json.dumps({"type": "object", "properties": {"ok": {"type": "boolean"}}})
        run, finish, summary = self.job(self.job_env(prompt="x", schema=schema))
        self.assertEqual(run.returncode, 1)
        self.assertIn("completed without structured output", summary.splitlines()[0])
        self.setUp()
        run, finish, summary = self.job(self.job_env(prompt='x [[fake:schema:{"ok": true}]]', schema=schema))
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn('```json\n{\n  "ok": true\n}\n```', summary)

    def test_a_timeout_is_red(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:silent:30]]"), timeout=1)
        self.assertEqual((run.returncode, finish.returncode), (1, 0))
        self.assertTrue(summary.startswith("# ❌ nightly · timed_out\n"))

    def test_a_cancel_stops_the_worker_and_still_leaves_a_summary(self):
        env = self.job_env(prompt="x [[fake:sleep:60]]")
        proc = subprocess.Popen([sys.executable, str(ENTRY), *self.args("run")], cwd=self.project, env={**self.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.wait_for(lambda: [m for m in self.scheduled_runs() if m.get("claude_pid")], what="the worker to start")
        # The runner cancels a step with SIGINT to its entry process, then SIGTERM, then kills its tree (probe 2); the worker's own process group is not part of it.
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=30)
        finish = self.step("finish", env)
        summary = Path(env["GITHUB_STEP_SUMMARY"]).read_text()
        self.assertEqual(finish.returncode, 0, finish.stdout)
        (meta,) = self.scheduled_runs()
        self.assertEqual(meta["state"], "interrupted")
        self.assertTrue(summary.startswith("# ⏹ nightly · interrupted\n"))
        self.assertIn("**Cancelled.**", summary)
        self.assertNotIn("::error title=nightly failed", finish.stdout)

    def test_a_local_stop_is_red(self):
        env = self.job_env(prompt="x [[fake:sleep:60]]")
        proc = subprocess.Popen([sys.executable, str(ENTRY), *self.args("run")], cwd=self.project, env={**self.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        meta = self.wait_for(lambda: next(iter(m for m in self.scheduled_runs() if m.get("claude_pid")), None), what="the worker to start")
        self.cli_json("stop", "--run", meta["run_id"])
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 1, out)
        finish = self.step("finish", env)
        summary = Path(env["GITHUB_STEP_SUMMARY"]).read_text()
        self.assertEqual(finish.returncode, 0)
        self.assertIn("[!CAUTION]", summary)

    def test_check_starts_no_worker(self):
        env = self.job_env(mode="check")
        run, finish, summary = self.job(env)
        self.assertEqual((run.returncode, finish.returncode), (0, 0), run.stdout)
        self.assertEqual(self.worker_calls(), [])
        self.assertTrue(summary.startswith("# 🔎 nightly · check passed\n"), summary[:100])
        self.assertIn("| **login** | ✅", summary)
        self.setUp()
        env = self.job_env(mode="check", extra={"FAKE_CLAUDE_AUTH": json.dumps({"loggedIn": False, "authMethod": "none"})})
        run, finish, summary = self.job(env)
        self.assertEqual((run.returncode, finish.returncode), (1, 0))
        self.assertTrue(summary.startswith("# 🔎 nightly · check failed\n"))
        self.assertIn("not logged in", summary)

    def test_the_project_gone(self):
        gone = self.root / "moved-away"
        env = self.job_env()
        run, finish, summary = self.job(env, project=gone)
        self.assertEqual((run.returncode, finish.returncode), (1, 0))
        self.assertIn("::error title=nightly%3A project missing::", run.stdout)
        self.assertFalse(gone.exists(), "no registry is created where the project was")
        self.assertIn("project missing", summary.splitlines()[0])
        self.assertIn("--project <new path>", summary)

    def test_an_unreadable_run_fails_the_finish_step_but_leaves_a_summary(self):
        env = self.job_env(prompt="x")
        self.assertEqual(self.step("run", env).returncode, 0)
        (meta,) = self.scheduled_runs()
        (self.run_dir(meta["run_id"]) / "meta.json").write_text("{not json")
        finish = self.step("finish", env)
        self.assertEqual(finish.returncode, 1, finish.stdout)
        summary = Path(env["GITHUB_STEP_SUMMARY"]).read_text()
        self.assertIn("could not be confirmed stopped", summary)

    def test_an_unwritable_step_summary_fails_the_finish_step(self):
        env = self.job_env(prompt="x")
        env["GITHUB_STEP_SUMMARY"] = str(self.root / "no-such-dir" / "summary")
        run = self.step("run", env)
        finish = self.step("finish", env)
        self.assertEqual((run.returncode, finish.returncode), (0, 1))
        (meta,) = self.scheduled_runs()
        self.assertTrue((self.run_dir(meta["run_id"]) / "summary.md").exists(), "the local copy is still kept")


class Slots(Job):
    """K4: automatic triggers fill a slot once; manual runs and re-runs always run."""

    def auto(self, run_id, source="dispatcher", event="workflow_dispatch", attempt=1, prompt="x", now=LATER):
        env = self.job_env(run_id=run_id, attempt=attempt, source=source, event=event, prompt=prompt, now=now)
        run, finish, summary = self.job(env)
        return run, summary

    def test_a_late_duplicate_is_skipped(self):
        run, _ = self.auto("1")
        self.assertEqual(run.returncode, 0)
        run, summary = self.auto("2", source="", event="schedule")
        self.assertEqual(run.returncode, 0)
        self.assertIn("skipped: slot 2026-11-17 03:00 KST already ran", run.stdout)
        self.assertTrue(summary.startswith("# ⏭ nightly · skipped\n"))
        self.assertEqual(len(self.worker_calls()), 1)

    def test_manual_runs_always_run(self):
        self.auto("1")
        for n in ("2", "3"):
            self.job(self.job_env(run_id=n))
        self.assertEqual(len(self.worker_calls()), 3)

    def test_a_rerun_runs_whatever_the_first_attempt_was(self):
        self.auto("1")
        run, summary = self.auto("2")  # skipped
        self.assertEqual(len(self.worker_calls()), 1)
        run, summary = self.auto("2", attempt=2)
        self.assertEqual(len(self.worker_calls()), 2, run.stdout)
        self.assertIn("re-run (attempt 2)", summary)

    def test_a_failed_read_only_slot_is_retried_once(self):
        run, _ = self.auto("1", prompt="x [[fake:auth_fail]]")
        self.assertEqual(run.returncode, 1)
        run, summary = self.auto("2", source="", event="schedule", prompt="x [[fake:auth_fail]]")
        self.assertEqual(len(self.worker_calls()), 2, run.stdout)
        self.assertIn("retry of [the run that failed]", summary)
        run, _ = self.auto("3", source="", event="schedule")
        self.assertEqual(len(self.worker_calls()), 2)
        self.assertIn("skipped", run.stdout)

    def test_the_retry_of_a_refused_start_says_so(self):
        env = self.job_env(run_id="1", source="dispatcher", extra={"FAKE_CLAUDE_VERSION": "1.0.0"})
        run, finish, summary = self.job(env)
        self.assertEqual(run.returncode, 1)
        run, summary = self.auto("2", source="", event="schedule")
        self.assertIn("retry of [the run that failed](https://github.com/someone/project/actions/runs/1)", summary)

    def test_a_failed_write_slot_is_not_retried(self):
        self.profile = "write"
        self.auto("1", prompt="x [[fake:auth_fail]]")
        run, _ = self.auto("2", source="", event="schedule")
        self.assertEqual(len(self.worker_calls()), 1)

    def test_a_lost_state_file_is_rebuilt_from_the_runs(self):
        self.auto("1")
        shutil.rmtree(self.runs_dir() / ".schedules" / "nightly")
        run, _ = self.auto("2", source="", event="schedule")
        self.assertIn("skipped", run.stdout)
        self.assertEqual(len(self.worker_calls()), 1)

    def test_a_one_off_is_dropped_26_hours_after_its_time(self):
        env = self.job_env(run_id="1", source="dispatcher", now=SLOT + 27 * 3600)
        run, finish, summary = self.job(env, at="2026-11-17T03:00")
        self.assertEqual(run.returncode, 0)
        self.assertIn("more than 26 hours ago", run.stdout)
        self.assertEqual(self.worker_calls(), [])

    def test_two_triggers_for_one_slot_at_once_start_one_worker(self):
        procs = []
        for n in ("1", "2"):
            env = self.job_env(run_id=n, source="dispatcher", prompt="x [[fake:silent:1]]")
            procs.append(subprocess.Popen([sys.executable, str(ENTRY), *self.args("run")], cwd=self.project, env={**self.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        both = [p.communicate(timeout=120) for p in procs]
        self.assertEqual(len(self.worker_calls()), 1, both)
        outs = [o for o, _ in both]
        self.assertEqual(sum("skipped" in o for o in outs), 1, both)


class Worker(Job):
    """What the worker gets: the schedule's origin, its first line, and none of the job's handles."""

    def test_the_job_handles_stay_with_the_job(self):
        self.job(self.job_env(prompt="x"))
        (call,) = self.worker_calls()
        for k in ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY", "GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_SCHEDULE_PROMPT"):
            self.assertNotIn(k, call["env"], k)
        self.assertEqual(call["env"]["RUNNER_TRACKING_ID"], "github_tracking")

    def test_it_is_told_nobody_watches(self):
        self.job(self.job_env(prompt="x"))
        (call,) = self.worker_calls()
        first = call["messages"][0]["message"]["content"]
        self.assertIn("This is a scheduled run of nightly (manual,", first)
        self.assertIn("GitHub Actions run summary in someone/project", first)
        (meta,) = self.scheduled_runs()
        self.assertEqual({k: meta["origin"][k] for k in ("name", "trigger", "job")}, {"name": "nightly", "trigger": "manual", "job": "44006368956-1"})

    def test_worker_text_cannot_issue_workflow_commands(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:reply:::error::forged]]"))
        lines = run.stdout.splitlines()
        token = lines[0].split("::stop-commands::", 1)[1]
        forged = lines.index("msg ::error::forged")
        state = None
        for line in lines[:forged]:
            if line == f"::stop-commands::{token}":
                state = "stopped"
            elif line == f"::{token}::":
                state = "reading"
        self.assertEqual(state, "stopped", "the worker's text reached the log while the runner read workflow commands")

    def test_attention_is_a_warning_not_a_stop(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:silent:5]]"))
        self.assertEqual(run.returncode, 0)
        self.assertIn("::warning title=nightly%3A stalled::", run.stdout)
        self.assertIn("needed attention while it ran", summary)


class Trees(Job):
    """K27 and K10: what changed during the run, in the checkout or in its own worktree."""

    profile = "write"

    def test_changes_are_what_the_run_changed(self):
        (self.project / "README.md").write_text("edited before\n")
        (self.project / "keep.txt").write_text("untouched untracked\n")
        git(self.project, "add", "keep.txt")
        git(self.project, "commit", "-q", "-m", "keep")
        (self.project / "keep.txt").write_text("changed before, left alone\n")
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:README.md]]"))
        changes = summary.split("<b>Changes</b>", 1)[1].split("</details>", 1)[0]
        self.assertIn(" M README.md  (already modified before the run)", changes)
        self.assertNotIn("keep.txt", changes, "a file changed before the run and left alone is not the run's")
        self.assertIn("`main` @", summary)
        self.assertIn("2 uncommitted files when the run began", summary)

    def test_a_new_file_counts_its_lines(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:new.txt]]"))
        self.assertIn("?? new.txt  (new, 1 line)", summary)

    def test_a_change_to_a_clean_file_counts_its_lines(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:README.md]]"))
        self.assertIn(" M README.md", summary)
        self.assertIn("+1 −1", summary)

    def test_a_worktree_with_nothing_to_keep_is_removed(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:reply:read only]]"), worktree=True)
        self.assertEqual((run.returncode, finish.returncode), (0, 0), run.stdout + finish.stdout)
        self.assertIn("worktree `", summary)
        self.assertEqual(list((self.project / ".claude" / "worktrees").glob("*")) if (self.project / ".claude" / "worktrees").exists() else [], [])
        self.assertIn("nothing to keep and was removed", summary)
        self.assertEqual(self.cli_json("status")["groups"], [])

    def test_a_worktree_with_changes_is_kept_and_named(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:notes.md]]"), worktree=True)
        self.assertEqual((run.returncode, finish.returncode), (0, 0))
        changes = summary.split("<b>Changes</b>", 1)[1].split("</details>", 1)[0]
        self.assertIn("?? notes.md", changes)
        self.assertIn("The worktree is kept", changes)
        self.assertIn("clean --group nightly-44006368956-1", changes)
        self.assertTrue((self.project / ".claude" / "worktrees" / "nightly-44006368956-1-1" / "notes.md").exists())
        self.assertFalse((self.project / "notes.md").exists(), "the checkout is not touched")

    def test_a_refused_worktree_start_releases_its_group(self):
        run, finish, summary = self.job(self.job_env(prompt="x", extra={"FAKE_CLAUDE_VERSION": "1.0.0"}), worktree=True)
        self.assertEqual((run.returncode, finish.returncode), (1, 0))
        self.assertEqual(self.cli_json("status")["groups"], [])

    def test_committed_work_in_a_worktree_is_shown_with_its_branch(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:notes.md]] [[fake:commit:work]]"), worktree=True)
        changes = summary.split("<b>Changes</b>", 1)[1].split("</details>", 1)[0]
        self.assertIn("notes.md", changes)
        self.assertIn("committed", changes)
        self.assertIn("worktree-nightly-44006368956-1-1", changes, "the branch that keeps the commits is named")
        self.assertNotIn("Nothing changed", changes)

    def test_committed_work_in_the_checkout_is_listed(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:new.txt]] [[fake:commit:work]]"))
        changes = summary.split("<b>Changes</b>", 1)
        head, body = changes[1].split("</summary>", 1)
        self.assertIn("1 file changed during the run", head)
        self.assertIn("committed", head)
        self.assertIn("new.txt", body.split("</details>", 1)[0])
        self.assertIn("HEAD moved", body)

    def test_a_file_committed_and_changed_again_is_one_file(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:new.txt]] [[fake:commit:work]] [[fake:write_after:new.txt]]"))
        head = summary.split("<b>Changes</b>", 1)[1].split("</summary>", 1)[0]
        self.assertIn("1 file changed during the run", head)

    def test_a_file_committed_then_deleted_says_so(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:write:new.txt]] [[fake:commit:work]] [[fake:delete_after:new.txt]]"))
        head, body = summary.split("<b>Changes</b>", 1)[1].split("</summary>", 1)
        self.assertIn("committed, then deleted", body.split("</details>", 1)[0])
        self.assertIn("uncommitted", head, "a deletion after the commit is not committed")

    def test_a_branch_switch_without_a_commit_is_shown(self):
        run, finish, summary = self.job(self.job_env(prompt="x [[fake:branch:another]]"))
        self.assertIn("HEAD moved during the run: `main @", summary)
        self.assertIn("another @", summary)

    def test_a_group_name_held_by_another_batch_is_refused_and_left_alone(self):
        self.cli_json("batch", "--group", "nightly-44006368956-1", "--task", "x", "--profile", "read-only")
        run, finish, summary = self.job(self.job_env(prompt="x"), worktree=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn("not started", summary.splitlines()[0])
        self.assertEqual(self.cli_json("status", "--group", "nightly-44006368956-1")["group"], "nightly-44006368956-1")

    def test_a_worktree_needs_a_commit(self):
        shutil.rmtree(self.project / ".git")
        git(self.project, "init", "-q", "-b", "main")
        run, finish, summary = self.job(self.job_env(prompt="x"), worktree=True)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(self.worker_calls(), [])
        self.assertIn("needs a commit", summary)
        self.assertNotIn("[!WARNING]", summary, "no group was ever made, so there is nothing to clean or warn about")


class HandOver(Job):
    """K19: Finish finds the run by its job even when Run died before `start` returned."""

    def test_run_killed_while_starting(self):
        env = self.job_env(prompt="x [[fake:sleep:60]]", extra={"CLAUDE_SKILL_TEST_TIMINGS": json.dumps({**FAST_TIMINGS, "pause_after_publish": 3})})
        proc = subprocess.Popen([sys.executable, str(ENTRY), *self.args("run")], cwd=self.project, env={**self.env, **env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.wait_for(self.scheduled_runs, what="the run to be published")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        finish = self.step("finish", env)
        self.assertEqual(finish.returncode, 0, finish.stdout)
        (meta,) = self.scheduled_runs()
        self.assertEqual(meta["state"], "interrupted")
        self.assertEqual(self.worker_calls(), [], "the worker never ran")
