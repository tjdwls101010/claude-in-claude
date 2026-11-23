"""S5 for schedules: `schedule` and `unschedule` against real GitHub, a real self-hosted runner and real launchd, with workers on the real `claude` (haiku). Skipped unless CLAUDE_SKILL_REAL=1 and CLAUDE_SKILL_REAL_GITHUB=1.

Needs CLAUDE_SKILL_REAL_SCHEDULE_PROJECT: a checkout of a PRIVATE repository whose self-hosted runner runs as a service on this Mac and can read the Claude login (its `schedule` reply lists no `runner.problems`). The test commits workflow files to that repository's default branch, installs LaunchAgents on this Mac, starts real jobs and workers, and removes its schedules again at the end (also when it fails). It takes about 20 minutes. The project checkout must be on its default branch with nothing in the way: the tests check that what lands on GitHub reaches it.

The one-off has the shape of a name a person gives — underscores, a capital, Korean — so the name's whole path is real: the file GitHub registers, the dispatcher launchd fires, the arguments the runner hands the steps, the worktree group and the summary's title.

Run from tests/: CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1 CLAUDE_SKILL_REAL_SCHEDULE_PROJECT=<checkout> python3 -m unittest smoke_real_schedule -v
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from support.harness import ENTRY

REAL = os.environ.get("CLAUDE_SKILL_REAL") == "1" and os.environ.get("CLAUDE_SKILL_REAL_GITHUB") == "1"
PROJECT = os.environ.get("CLAUDE_SKILL_REAL_SCHEDULE_PROJECT")


@unittest.skipUnless(REAL and PROJECT, "set CLAUDE_SKILL_REAL=1, CLAUDE_SKILL_REAL_GITHUB=1 and CLAUDE_SKILL_REAL_SCHEDULE_PROJECT")
class RealSchedule(unittest.TestCase):
    def setUp(self):
        self.project = Path(PROJECT).resolve()
        self.token = secrets.token_hex(2)
        self.name = f"smoke-{self.token}"
        self.once = f"Smoke_{self.token}_일회성"
        self.addCleanup(self.cleanup)
        self.repo = None

    def cleanup(self):
        for name in (self.name, self.once):
            self.cli("unschedule", "--name", name)

    def env(self):
        env = dict(os.environ)
        for k in ("CLAUDE_SKILL_TEST_TIMINGS", "CLAUDE_SKILL_TEST_NOW"):
            env.pop(k, None)
        return env

    def cli(self, *args, input=None):
        return subprocess.run(["uv", "run", "--quiet", str(ENTRY), *args, "--project", str(self.project)], cwd=self.project, capture_output=True, text=True, env=self.env(), timeout=300, input=input)

    def cli_json(self, *args, expect=0, input=None):
        proc = self.cli(*args, input=input)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout.splitlines()[0])

    def gh(self, *args, check=True):
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
        if check and proc.returncode:
            raise AssertionError(f"gh {' '.join(args)}: {proc.stderr}")
        return proc.stdout

    def runs(self, name):
        return json.loads(self.gh("run", "list", "--repo", self.repo, "--workflow", f"{name}.yml", "--limit", "20", "--json", "databaseId,displayTitle,status,conclusion,event,createdAt"))

    def workflow_state(self, name):
        return json.loads(self.gh("api", f"repos/{self.repo}/actions/workflows/{quote(name + '.yml', safe='')}"))["state"]

    def dispatch(self, name, *fields):
        before = {r["databaseId"] for r in self.runs(name)}
        self.gh("workflow", "run", f"{name}.yml", "--repo", self.repo, *[x for f in fields for x in ("-f", f)])
        return self.new_run(name, before, 90)

    def new_run(self, name, before, seconds):
        end = time.time() + seconds
        while time.time() < end:
            fresh = [r for r in self.runs(name) if r["databaseId"] not in before]
            if fresh:
                return fresh[0]["databaseId"]
            time.sleep(5)
        self.fail(f"no new run of {name}.yml within {seconds} s")

    def watch(self, run_id):
        # `gh run watch` can come back before the run ends (seen on a run dispatched seconds earlier), so the end is read from the run itself.
        end = time.time() + 1200
        while True:
            subprocess.run(["gh", "run", "watch", str(run_id), "--repo", self.repo], capture_output=True, timeout=1200)
            run = json.loads(self.gh("run", "view", str(run_id), "--repo", self.repo, "--json", "status,conclusion,displayTitle"))
            if run["status"] == "completed" or time.time() > end:
                return run
            time.sleep(5)

    def state(self, name):
        return json.loads((self.registry / ".schedules" / name / "state.json").read_text())

    def run_summary(self, name, gh_run, attempt=1):
        job = self.state(name)["jobs"][f"{gh_run}-{attempt}"]
        if job.get("run_id"):
            return (self.registry / job["run_id"] / "summary.md").read_text(), job
        return (self.registry / ".schedules" / name / f"summary-{gh_run}-{attempt}.md").read_text(), job

    def schedule(self, name, prompt, *flags):
        return self.cli_json("schedule", "--name", name, prompt, *flags)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True, timeout=120, check=True).stdout.strip()

    def land(self, rel, text, message):
        """A commit on GitHub's default branch through the Contents API, as a pull request a worker merged leaves one; its sha."""
        body = json.dumps({"message": message, "content": base64.b64encode(text.encode()).decode()})
        proc = subprocess.run(["gh", "api", "-X", "PUT", f"repos/{self.repo}/contents/{quote(rel)}", "--input", "-"], input=body, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["commit"]["sha"]

    def started(self, name, gh_run):
        """Wait until the job's worker has started, so what lands next lands while it runs."""
        end = time.time() + 300
        while time.time() < end:
            try:
                if self.state(name)["jobs"].get(f"{gh_run}-1", {}).get("run_id"):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(3)
        self.fail(f"the worker of run {gh_run} did not start")

    def test_what_lands_on_github_reaches_the_checkout(self):
        # K30, on the real runner: its service must reach GitHub with the person's login (the job's token, which git would otherwise use, cannot read the repository).
        reply = self.schedule(self.name, "Run the shell command: sleep 60 — then reply with the single word done.", "--cron", "0 4 1 1 *", "--profile", "read-only", "--model", "haiku", "--effort", "low", "--timeout", "600")
        self.repo = reply["repo"]
        self.registry = self.project / ".claude-runs"
        self.assertEqual((reply["local"]["status"], reply["local"]["contains_commit"]), ("updated", True), reply["local"])
        self.assertTrue((self.project / ".github" / "workflows" / f"{self.name}.yml").exists(), "the committed workflow is in the checkout")

        run = self.dispatch(self.name)
        self.started(self.name, run)
        sha = self.land(f"smoke-landed-{self.token}.md", "landed while the run ran\n", f"smoke: landed during {self.name}")
        self.assertEqual(self.watch(run)["conclusion"], "success")
        summary, _ = self.run_summary(self.name, run)
        row = next(l for l in summary.splitlines() if l.startswith("| **Local checkout** |"))
        self.assertIn("fast-forwarded", row, summary[:1500])
        self.assertEqual(self.git("rev-parse", "HEAD"), sha)
        self.assertTrue((self.project / f"smoke-landed-{self.token}.md").exists())

        blocker = self.project / f"smoke-blocked-{self.token}.md"
        blocker.write_text("mine\n")
        # Only while it is the test's own untracked file: by the end it is the tracked one GitHub sent, which stays.
        self.addCleanup(lambda: subprocess.run(["git", "-C", str(self.project), "ls-files", "--error-unmatch", blocker.name], capture_output=True).returncode == 0 or blocker.unlink(missing_ok=True))
        run = self.dispatch(self.name)
        self.started(self.name, run)
        blocked = self.land(blocker.name, "theirs\n", f"smoke: in the way of {self.name}")
        self.assertEqual(self.watch(run)["conclusion"], "success", "an update left undone does not fail the job")
        summary, _ = self.run_summary(self.name, run)
        self.assertIn("Your checkout was not updated from GitHub", summary)
        self.assertIn(blocker.name, summary)
        self.assertEqual(blocker.read_text(), "mine\n")
        self.assertEqual(self.git("rev-parse", "HEAD"), sha)

        blocker.unlink()
        again = self.cli_json("schedule", "--name", self.name)
        self.assertEqual((again["workflow"]["status"], again["local"]["status"]), ("unchanged", "updated"), "calling again completes what was left undone")
        self.assertEqual(self.git("rev-parse", "HEAD"), blocked)

    def test_the_whole_life_of_a_schedule(self):
        soon = datetime.now() + timedelta(minutes=3)
        reply = self.schedule(self.name, "List the files in this directory and reply with one line saying how many there are.", "--cron", f"{soon.minute} {soon.hour} * * *", "--profile", "read-only", "--model", "haiku", "--effort", "low", "--timeout", "600")
        self.repo = reply["repo"]
        self.registry = self.project / ".claude-runs"
        self.assertEqual((reply["workflow"]["status"], reply["dispatcher"]["status"]), ("committed", "installed"), reply)
        self.assertEqual(reply["runner"]["problems"], [], "the runner must be ready for this smoke")
        self.assertEqual(reply["workflow"]["path"], f".github/workflows/{self.name}.yml")
        self.assertEqual(self.workflow_state(self.name), "active", "GitHub accepted the workflow file")

        check = self.dispatch(self.name, "mode=check")
        self.assertEqual(self.watch(check)["conclusion"], "success")
        self.assertIn("check passed", self.run_summary(self.name, check)[0].splitlines()[0])

        manual = self.dispatch(self.name)
        self.assertEqual(self.watch(manual)["conclusion"], "success")
        summary, job = self.run_summary(self.name, manual)
        self.assertTrue(summary.startswith(f"# ✅ {self.name} · completed"), summary[:200])
        self.assertTrue((self.registry / job["run_id"] / "meta.json").exists(), "the run is in the project's registry")

        # The dispatcher fires at `soon` on this Mac's clock.
        before = {r["databaseId"] for r in self.runs(self.name)}
        fired = self.new_run(self.name, before, 300)
        result = self.watch(fired)
        self.assertEqual(result["conclusion"], "success")
        self.assertIn("dispatcher", result["displayTitle"])
        self.assertEqual(self.state(self.name)["jobs"][f"{fired}-1"]["trigger"], "dispatcher")

        late = self.dispatch(self.name, "source=dispatcher")
        self.assertEqual(self.watch(late)["conclusion"], "success")
        self.assertTrue(self.run_summary(self.name, late)[0].startswith(f"# ⏭ {self.name} · skipped"))

        self.schedule(self.name, "Run the shell command: sleep 120 — then reply with the single word done.")
        long_run = self.dispatch(self.name)
        end = time.time() + 180
        while time.time() < end:
            job = self.state(self.name)["jobs"].get(f"{long_run}-1") or {}
            if job.get("run_id") and '"Bash"' in (self.registry / job["run_id"] / "events.jsonl").read_text():
                break
            time.sleep(3)
        self.gh("run", "cancel", str(long_run), "--repo", self.repo)
        self.assertEqual(self.watch(long_run)["conclusion"], "cancelled")
        summary, job = self.run_summary(self.name, long_run)
        self.assertEqual(json.loads((self.registry / job["run_id"] / "meta.json").read_text())["state"], "interrupted")
        self.assertIn("**Cancelled.**", summary)

        self.schedule(self.name, "Create the file smoke-notes.md containing one line: written by a scheduled worker. Then reply done.", "--profile", "write", "--worktree")
        writer = self.dispatch(self.name)
        self.assertEqual(self.watch(writer)["conclusion"], "success")
        summary, job = self.run_summary(self.name, writer)
        self.assertIn("smoke-notes.md", summary)
        self.assertIn("The worktree is kept", summary)
        self.assertFalse((self.project / "smoke-notes.md").exists(), "the checkout itself is untouched")
        group = job["group"]
        self.cli_json("clean", "--group", group, "--force")

        at = datetime.now() + timedelta(minutes=3)
        once = self.schedule(self.once, "Reply with the single word once.", "--at", at.strftime("%Y-%m-%dT%H:%M"), "--profile", "write", "--worktree", "--model", "haiku", "--effort", "low")
        self.assertEqual((once["name"], once["workflow"]["path"]), (self.once, f".github/workflows/Smoke_{self.token}_일회성.yml"))
        label = once["dispatcher"]["label"]
        self.assertEqual(label, f"claude-schedule.{self.repo.replace('/', '-')}.Smoke_{self.token}_일회성")
        listed = {r["name"]: r for r in self.cli_json("schedule", "--list")["schedules"]}
        self.assertEqual((listed[self.once]["file"], listed[self.once]["dispatcher"]), (f"Smoke_{self.token}_일회성.yml", "loaded"))
        before = {r["databaseId"] for r in self.runs(self.once)}
        fired = self.new_run(self.once, before, 300)
        result = self.watch(fired)
        self.assertEqual(result["conclusion"], "success")
        self.assertEqual(result["displayTitle"], f"Smoke_{self.token}_일회성 · dispatcher", "the title in Actions is the name as given")
        summary, job = self.run_summary(self.once, fired)
        self.assertEqual(summary.splitlines()[0], f"# ✅ Smoke\\_{self.token}\\_일회성 · completed")
        self.assertEqual(job["group"], f"smoke-{self.token}-{fired}-1", "the worktree group is the name's ASCII slug")
        self.assertIn("nothing to keep and was removed", summary)
        self.assertEqual(self.workflow_state(self.once), "disabled_manually")
        self.assertFalse((Path.home() / "Library" / "LaunchAgents" / f"{label}.plist").exists())

        for name in (self.name, self.once):
            gone = self.cli_json("unschedule", "--name", name)
            self.assertIn(gone["workflow"]["status"], ("deleted",), gone)
        missing = subprocess.run(["gh", "api", f"repos/{self.repo}/contents/.github/workflows/{self.name}.yml"], capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(any(self.token in p.name for p in (Path.home() / "Library" / "LaunchAgents").glob("claude-schedule.*.plist")))


if __name__ == "__main__":
    unittest.main()
