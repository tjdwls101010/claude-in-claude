"""`schedule`, `unschedule` and `schedule --list` through the CLI with a fake `gh` (answers shaped like captured real ones, over a simulated private repository) and a fake `launchctl` (real messages and exit codes), in a private HOME: what gets committed and installed, merging a second call into the first (K2), the halves of a failure (K12), the refusals, the one-off's end (K8) and two calls at once (S3). The expected workflow is written by hand in the shape GitHub accepted (probe 11, stage PR ②)."""

from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import sys
import threading
from pathlib import Path

from support.harness import ENTRY, FIXTURES, SUPPORT, Sandbox, engine, git

registry = engine("claude.registry")

REPO = "someone/project"
NOW = None  # set below from this Mac's zone
TZ = os.path.realpath("/etc/localtime").split("/zoneinfo/", 1)[1]
LABEL = "claude-schedule.someone-project.nightly"
NOW = int(__import__("datetime").datetime(2026, 11, 17, 5, 47, tzinfo=__import__("zoneinfo").ZoneInfo(TZ)).timestamp())  # 05:47 on 2026-11-17 here


class Scheduling(Sandbox):
    def setUp(self):
        super().setUp()
        self.gh_state = self.root / "gh"
        self.lc_state = self.root / "launchctl"
        self.gh_state.mkdir()
        self.lc_state.mkdir()
        self.env["PATH"] = os.pathsep.join([str(SUPPORT / "fake_gh"), str(SUPPORT / "fake_launchctl"), self.env["PATH"]])
        self.env.update({"FAKE_GH_STATE": str(self.gh_state), "FAKE_GH_FIXTURES": str(FIXTURES / "github"), "FAKE_LAUNCHCTL_STATE": str(self.lc_state), "CLAUDE_SKILL_TEST_NOW": str(NOW)})
        git(self.project, "remote", "add", "origin", f"https://github.com/{REPO}.git")
        self.world({"auth": "ok", "repos": {REPO: {"private": True, "default_branch": "main", "files": {}, "workflows": {}, "runners": [{"name": "mac", "status": "online"}]}}})

    def world(self, data=None, **change):
        path = self.gh_state / "world.json"
        if data is not None:
            path.write_text(json.dumps(data))
        w = json.loads(path.read_text())
        for k, v in change.items():
            w[k] = v
        path.write_text(json.dumps(w))
        return w

    def repo(self):
        return self.world()["repos"][REPO]

    def committed(self, name="nightly"):
        f = self.repo()["files"].get(f".github/workflows/claude-{name}.yml")
        return f["text"] if f else None

    def gh_calls(self):
        out = []
        for p in sorted((self.gh_state / "calls").glob("*.json")):
            out.append(json.loads(p.read_text()))
        return out

    def lc_calls(self):
        return [json.loads(p.read_text())["argv"] for p in sorted((self.lc_state / "calls").glob("*.json"))] if (self.lc_state / "calls").exists() else []

    def definition(self, name="nightly"):
        return (registry.schedule_state(str(self.runs_dir()), name) or {}).get("definition")

    def plist(self, label=LABEL):
        p = self.home / "Library" / "LaunchAgents" / f"{label}.plist"
        return plistlib.loads(p.read_bytes()) if p.exists() else None

    def schedule(self, *args, expect=0, input=None):
        return self.cli_json("schedule", "--name", "nightly", *args, expect=expect, input=input)

    def new(self, *extra, prompt="Review yesterday's commits and report what looks risky.", **kw):
        return self.schedule(prompt, "--cron", "0 3 * * *", "--profile", "read-only", *extra, **kw)

    def expected_workflow(self, definition, prompt="Review yesterday's commits and report what looks risky.", cron="0 3 * * *", profile="read-only"):
        spec = {"at": None, "cli": str(ENTRY), "cron": cron, "definition": definition, "effort": "high", "model": "sonnet", "name": "nightly", "profile": profile, "project": str(self.project), "prompt": prompt, "runs_on": ["self-hosted"], "schema": None, "timeout": 3600, "timezone": TZ, "worktree": False}
        import shlex

        steps = f"--name nightly --project {shlex.quote(str(self.project))} --profile {profile} --model sonnet --effort high --timeout 3600 --cron '{cron}' --timezone {TZ} --workflow claude-nightly.yml --definition {definition}"

        def run(step):
            # The step's command: shell words, written as a YAML double-quoted (JSON) string.
            return json.dumps(f"uv run {shlex.quote(str(ENTRY))} __scheduled {step} {steps}", ensure_ascii=False)

        env = f"""          CLAUDE_SCHEDULE_MODE: ${{{{ inputs.mode }}}}
          CLAUDE_SCHEDULE_SOURCE: ${{{{ inputs.source }}}}
          CLAUDE_SCHEDULE_PROMPT: |2-
            {prompt}"""
        return f"""# Written by the claude skill's `schedule` command. Run it again with the same --name to change it; `unschedule` removes it.
# spec: {json.dumps(spec, ensure_ascii=False, sort_keys=True)}
name: claude · nightly
run-name: nightly · ${{{{ inputs.mode == 'check' && 'check' || inputs.source || github.event_name }}}}
on:
  schedule:
    - cron: '{cron}'
      timezone: {TZ}
  workflow_dispatch:
    inputs:
      mode:
        description: run starts the worker; check only verifies that this runner can log in and start one
        type: choice
        options: [run, check]
        default: run
      source:
        description: Leave empty for a manual run. The local dispatcher sets it so that a late duplicate is skipped.
        type: string
        required: false
permissions: {{}}
concurrency:
  group: claude-nightly
  cancel-in-progress: false
  queue: max
jobs:
  run:
    runs-on: ["self-hosted"]
    timeout-minutes: 70
    steps:
      - name: Run
        env:
{env}
        run: {run("run")}
      - name: Finish
        if: always()
        env:
{env}
          GH_TOKEN: ${{{{ github.token }}}}
        run: {run("finish")}
"""


class Schedule(Scheduling):
    def test_a_new_schedule_commits_the_workflow_and_installs_the_dispatcher(self):
        reply = self.new()
        text = self.committed()
        definition = json.loads(text.splitlines()[1][len("# spec: "):])["definition"]
        self.maxDiff = None
        self.assertEqual(text, self.expected_workflow(definition))
        put = next(c for c in self.gh_calls() if "PUT" in c["argv"] and "contents" in " ".join(c["argv"]))
        body = json.loads(put["stdin"])
        self.assertEqual((body["branch"], body["message"]), ("main", f"Schedule Claude worker nightly: 0 3 * * * ({TZ})"))
        self.assertEqual(base64.b64decode(body["content"]).decode(), text)
        plist = self.plist()
        gh = self.gh_calls()[0]  # the fake's own path is what the plist names
        self.assertEqual(plist["ProgramArguments"][1:], ["workflow", "run", "claude-nightly.yml", "--repo", REPO, "--ref", "main", "-f", "source=dispatcher"])
        self.assertTrue(plist["ProgramArguments"][0].endswith("fake_gh/gh"))
        self.assertEqual(plist["StartCalendarInterval"], [{"Minute": 0, "Hour": 3}])
        self.assertEqual(plist["StandardOutPath"], str(self.home / "Library" / "Logs" / "claude-schedule" / "someone-project.nightly.log"))
        self.assertIn(["bootstrap", f"gui/{os.getuid()}", str(self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist")], self.lc_calls())
        self.assertEqual(reply["workflow"]["status"], "committed")
        self.assertEqual(reply["dispatcher"]["status"], "installed")
        self.assertEqual(reply["fires"]["next"][0], f"2026-11-18 03:00 {'KST' if TZ == 'Asia/Seoul' else reply['fires']['next'][0].split()[-1]}")
        self.assertEqual(reply["next"]["command"], f"gh workflow run claude-nightly.yml --repo {REPO} -f mode=check")
        self.assertEqual(self.definition(), definition)

    def test_calling_again_changes_only_what_is_given(self):
        self.new()
        first = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        reply = self.schedule("--cron", "30 4 * * 1-5")
        spec = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        self.assertEqual((spec["cron"], spec["prompt"], spec["profile"]), ("30 4 * * 1-5", first["prompt"], "read-only"))
        self.assertNotEqual(spec["definition"], first["definition"])
        self.assertEqual(self.plist()["StartCalendarInterval"], [{"Minute": 30, "Hour": 4, "Weekday": d} for d in (1, 2, 3, 4, 5)])
        again = self.schedule()
        self.assertEqual(again["workflow"]["status"], "unchanged")
        self.assertEqual(json.loads(self.committed().splitlines()[1][len("# spec: "):])["definition"], spec["definition"])

    def test_an_empty_stdin_does_not_touch_the_prompt(self):
        self.new()
        before = self.committed()
        reply = self.schedule(input="")
        self.assertEqual(reply["workflow"]["status"], "unchanged")
        self.assertEqual(self.committed(), before)
        self.schedule("--prompt-file", "-", input="From stdin.\n")
        self.assertIn('"prompt": "From stdin.\\n"', self.committed())

    def test_a_disabled_workflow_is_enabled_again(self):
        self.new()
        w = self.world()
        w["repos"][REPO]["workflows"]["claude-nightly.yml"] = "disabled_manually"
        self.world(w)
        reply = self.schedule("--profile", "write")
        self.assertTrue(reply["workflow"]["was_disabled"])
        self.assertEqual(self.repo()["workflows"]["claude-nightly.yml"], "active")

    def test_dry_run_writes_nothing(self):
        reply = self.new("--dry-run")
        self.assertIn("name: claude · nightly", reply["workflow_text"])
        self.assertEqual(plistlib.loads(reply["dispatcher_text"].encode())["Label"], LABEL)
        writes = [c for c in self.gh_calls() if any(m in c["argv"] for m in ("PUT", "DELETE"))]
        self.assertEqual(writes, [])
        self.assertEqual([c for c in self.lc_calls() if c[0] != "print"], [])
        self.assertIsNone(self.plist())

    def test_a_dispatcher_that_fails_leaves_the_committed_workflow_and_says_so(self):
        reply = self.cli_json("schedule", "--name", "nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only", env={"FAKE_LAUNCHCTL_FAIL": "bootstrap"})
        self.assertEqual((reply["workflow"]["status"], reply["dispatcher"]["status"]), ("committed", "failed"))
        self.assertIn("Bootstrap failed: 5", reply["dispatcher"]["error"])
        self.assertTrue(any("only GitHub's backup cron" in w for w in reply["warnings"]))

    def test_a_refused_commit_installs_nothing(self):
        self.world(protected=True)
        reply = self.new(expect=1)
        self.assertIn("Changes must be made through a pull request", reply["error"])
        self.assertIn("--dry-run", reply["instead"])
        self.assertEqual(sum(1 for c in self.gh_calls() if "PUT" in c["argv"]), 1, "a protected branch is not a race to retry")
        self.assertIsNone(self.plist())
        self.assertEqual([c for c in self.lc_calls() if c[0] == "bootstrap"], [])

    def test_losing_a_race_merges_and_retries_once(self):
        self.new()
        self.world(race=1)
        reply = self.new("--profile", "write")
        self.assertEqual(reply["workflow"]["status"], "committed", "the merged definition (now with --profile write) is committed on the second try")
        spec = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        self.assertEqual(spec["profile"], "write")
        self.assertEqual(self.definition(), spec["definition"])
        self.assertEqual(sum(1 for c in self.gh_calls() if "PUT" in c["argv"] and "contents" in " ".join(c["argv"])), 3)

    def test_after_a_race_the_dispatcher_fires_on_the_committed_time(self):
        self.new()
        self.world(race=1, race_cron="30 4 * * *")
        reply = self.schedule("--profile", "write")
        spec = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        self.assertEqual((spec["cron"], spec["profile"]), ("30 4 * * *", "write"))
        self.assertEqual(self.plist()["StartCalendarInterval"], [{"Minute": 30, "Hour": 4}])
        self.assertEqual(reply["fires"]["cron"], "30 4 * * *")
        self.assertEqual(reply["settings"]["profile"], "write")

    def test_awkward_paths_and_labels_reach_the_job_as_given(self):
        import shlex

        odd = self.root / "my proj #2: final"
        odd.mkdir()
        git(odd, "init", "-q", "-b", "main")
        git(odd, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "init")
        git(odd, "remote", "add", "origin", f"https://github.com/{REPO}.git")
        self.cli_json("schedule", "--name", "nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only", "--runs-on", "123", "--runs-on", "true", "--project", str(odd))
        text = self.committed()
        run = next(l for l in text.splitlines() if l.startswith("        run: ") and " run " in l)[len("        run: "):]
        self.assertTrue(run.startswith('"'), "the run line is a quoted YAML string")
        words = shlex.split(json.loads(run))
        self.assertEqual(words[words.index("--project") + 1], str(odd))
        self.assertIn('    runs-on: ["self-hosted", "123", "true"]', text)

    def test_the_repository_is_named_as_github_spells_it(self):
        git(self.project, "remote", "set-url", "origin", "https://github.com/Someone/Project.git")
        reply = self.new()
        self.assertEqual(reply["repo"], REPO)
        self.assertEqual(reply["dispatcher"]["label"], LABEL)
        self.assertIsNotNone(self.plist())

    def test_many_workflows_are_all_listed(self):
        self.new()
        w = self.world()
        for n in range(150):
            w["repos"][REPO]["workflows"][f"build-{n:03d}.yml"] = "active"  # sorted before claude-nightly.yml, so it lands on page 2
        self.world(w)
        rows = self.cli_json("schedule", "--list")["schedules"]
        self.assertEqual([r["name"] for r in rows], ["nightly"])
        w["repos"][REPO]["workflows"]["zzz.yml"] = "active"
        self.world(w)
        self.assertEqual(self.cli_json("schedule", "--list")["orphans"], [])

    def test_runner_problems_come_from_this_mac(self):
        rdir = self.root / "actions-runner"
        rdir.mkdir()
        (rdir / ".path").write_text("/usr/bin:/bin")
        (rdir / ".env").write_text("LANG=en_US.UTF-8\n")
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "actions.runner.someone-project.mac.plist").write_bytes(plistlib.dumps({"Label": "actions.runner.someone-project.mac", "WorkingDirectory": str(rdir), "SessionCreate": True}))
        reply = self.new("--dry-run")
        kinds = [p["problem"] for p in reply["runner"]["problems"]]
        self.assertEqual(kinds, ["session_create", "path_missing"])
        self.assertEqual(len(reply["runner"]["problems"][0]["fixes"]), 2, "both ways to give the service a login are offered")
        self.assertIn("uv, claude", reply["runner"]["problems"][1]["why"])
        (rdir / ".env").write_text("LANG=en_US.UTF-8\nCLAUDE_CODE_OAUTH_TOKEN=sk-x\n")
        self.assertEqual([p["problem"] for p in self.new("--dry-run")["runner"]["problems"]], ["path_missing"])
        self.world(repos={REPO: {**self.repo(), "runners": []}})
        self.assertEqual([p["problem"] for p in self.new("--dry-run")["runner"]["problems"]], ["none"])


class Refusals(Scheduling):
    def test_command_line(self):
        for args, why in [
            (("--name", "Nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only"), "--name"),
            (("--name", "a" * 25, "x", "--cron", "0 3 * * *", "--profile", "read-only"), "--name"),
            (("--name", "nightly", "--cron", "0 3 * * *", "--profile", "read-only"), "a prompt"),
            (("--name", "nightly", "x", "--profile", "read-only"), "--cron or --at"),
            (("--name", "nightly", "x", "--cron", "0 3 * * *"), "--profile"),
            (("--name", "nightly", "x", "--cron", "*/2 * * * *", "--profile", "read-only"), "5 minutes"),
            (("--name", "nightly", "x", "--cron", "0 3 * * MON", "--profile", "read-only"), "names"),
            (("--name", "nightly", "x", "--at", "2026-11-17T05:00", "--profile", "read-only"), "not in the future"),
            (("--name", "nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only", "--worktree"), "read-only"),
            (("--name", "nightly", "x\x07", "--cron", "0 3 * * *", "--profile", "read-only"), "control character"),
            (("--name", "nightly", "x", "--at", "2027-1-5T9:00", "--profile", "read-only"), "YYYY-MM-DDTHH:MM"),
            (("--name", "nightly", "x", "--cron", "0 3 30 2 *", "--profile", "read-only"), "never fires"),
        ]:
            with self.subTest(why=why):
                reply = self.cli_json("schedule", *args, expect=2)
                self.assertIn(why, reply["error"])
        reply = self.cli_json("schedule", "--name", "nightly", "x", "--cron", "0 3 * * *", "--at", "2026-12-01T03:00", "--profile", "read-only", expect=2)
        self.assertIn("not allowed with", reply["error"])
        self.assertEqual(self.committed(), None)

    def test_state(self):
        self.world(repos={REPO: {**self.repo(), "private": False}})
        self.assertIn("is public", self.new(expect=1)["error"])
        self.assertEqual(self.new("--public-ok")["workflow"]["status"], "committed")
        self.world(auth="none")
        self.assertIn("gh auth login", self.new(expect=1)["error"])
        self.world(auth="noscope")
        self.assertIn("workflow", self.new(expect=1)["error"])
        self.world(auth="ok")
        git(self.project, "remote", "set-url", "origin", "https://gitlab.com/someone/project.git")
        self.assertIn("no GitHub remote", self.new(expect=1)["error"])
        git(self.project, "remote", "set-url", "origin", f"git@github.com:{REPO}.git")
        w = self.world()
        w["repos"][REPO]["private"] = True
        w["repos"][REPO]["files"][".github/workflows/claude-mine.yml"] = {"text": "name: mine\non: push\n", "sha": "abc"}
        self.world(w)
        reply = self.cli_json("schedule", "--name", "mine", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1)
        self.assertIn("was not written by this skill", reply["error"])

    def test_a_refusal_writes_nothing_here_either(self):
        self.cli_json("schedule", "--name", "nightly", "--cron", "0 3 * * *", "--profile", "read-only", expect=2)
        self.assertFalse(self.runs_dir().exists(), "a refusal leaves no registry behind")

    def test_a_network_failure_is_not_sent_to_a_pull_request(self):
        self.world(offline=True)
        reply = self.new(expect=1)
        self.assertIn("error connecting", reply["error"])
        self.assertNotIn("pull request", reply.get("instead") or "")
        self.assertNotIn("nothing was written", reply.get("instead") or "", "a request that got no answer may still have been committed")

    def test_inside_a_worker(self):
        reply = self.cli_json("schedule", "--name", "nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1, env={"CLAUDE_SKILL_RUN": "r1"})
        self.assertIn("inside worker run", reply["error"])


class Unschedule(Scheduling):
    def test_a_workflow_with_a_spec_line_of_its_own_is_left_alone(self):
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/claude-mine.yml"] = {"text": "# spec: {}\nname: mine\non: push\n", "sha": "abc"}
        self.world(w)
        self.assertIn("was not written by this skill", self.cli_json("unschedule", "--name", "mine", expect=1)["error"])
        self.assertIn("was not written by this skill", self.cli_json("schedule", "--name", "mine", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1)["error"])

    def test_a_file_this_skill_did_not_write_is_left_alone(self):
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/claude-code-review.yml"] = {"text": "name: review\non: pull_request\n", "sha": "abc"}
        self.world(w)
        reply = self.cli_json("unschedule", "--name", "code-review", expect=1)
        self.assertIn("was not written by this skill", reply["error"])
        self.assertIn(".github/workflows/claude-code-review.yml", self.repo()["files"])

    def test_removes_both_halves(self):
        self.new()
        reply = self.cli_json("unschedule", "--name", "nightly")
        self.assertEqual((reply["dispatcher"]["status"], reply["workflow"]["status"]), ("removed", "deleted"))
        self.assertIsNone(self.committed())
        self.assertIsNone(self.plist())
        self.assertIsNone(registry.schedule_state(str(self.runs_dir()), "nightly"))
        again = self.cli_json("unschedule", "--name", "nightly")
        self.assertEqual((again["dispatcher"]["status"], again["workflow"]["status"]), ("absent", "absent"))

    def test_a_failure_of_one_half_is_reported_beside_the_other(self):
        self.new()
        reply = self.cli_json("unschedule", "--name", "nightly", env={"FAKE_LAUNCHCTL_FAIL": "bootout"})
        self.assertEqual((reply["dispatcher"]["status"], reply["workflow"]["status"]), ("failed", "deleted"))

    def test_a_live_run_keeps_the_state_without_its_definition(self):
        self.new()
        reply = self.start("x [[fake:sleep:30]]")
        meta_path = self.run_dir(reply["run_id"]) / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["origin"] = {"kind": "schedule", "name": "nightly", "job": "1-1"}
        meta_path.write_text(json.dumps(meta))
        out = self.cli_json("unschedule", "--name", "nightly")
        self.assertIn(reply["run_id"], out["note"])
        self.assertIsNone(self.definition())
        self.assertIsNotNone(registry.schedule_state(str(self.runs_dir()), "nightly"))
        self.cli_json("stop", "--run", reply["run_id"])


class Listing(Scheduling):
    def test_list(self):
        self.new()
        self.cli_json("schedule", "--name", "weekly", "y", "--cron", "0 9 * * 1", "--profile", "write")
        w = self.world()
        w["repos"][REPO]["workflows"]["claude-weekly.yml"] = "disabled_manually"
        self.world(w)
        (self.home / "Library" / "LaunchAgents" / "claude-schedule.someone-project.gone.plist").write_bytes(plistlib.dumps({"Label": "claude-schedule.someone-project.gone"}))
        text = self.committed().replace(str(ENTRY), "/nowhere/cli.py")
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/claude-nightly.yml"]["text"] = text
        self.world(w)
        out = self.cli_json("schedule", "--list")
        rows = {r["name"]: r for r in out["schedules"]}
        self.assertEqual((rows["nightly"]["state"], rows["weekly"]["state"]), ("active", "disabled"))
        self.assertEqual(rows["nightly"]["dispatcher"], "loaded")
        self.assertTrue(rows["nightly"]["stale_entry"])
        self.assertEqual(rows["nightly"]["stale_paths"], ["/nowhere/cli.py"])
        self.assertFalse(rows["weekly"]["stale_entry"])
        self.assertEqual([o["label"] for o in out["orphans"]], ["claude-schedule.someone-project.gone"])


class Races(Scheduling):
    def test_two_schedules_of_one_name_at_once(self):
        prompts = ["First prompt, all of it.", "Second prompt, all of it."]
        procs = [subprocess.Popen([sys.executable, str(ENTRY), "schedule", "--name", "nightly", p, "--cron", "0 3 * * *", "--profile", "read-only"], cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for p in prompts]
        outs = [p.communicate(timeout=120) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], outs)
        spec = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        self.assertIn(spec["prompt"], prompts)
        other = next(p for p in prompts if p != spec["prompt"])
        self.assertNotIn(other, self.committed(), "the committed workflow is one call's, whole")
        self.assertEqual(self.committed().count(spec["prompt"]), 3, "the spec line and both steps")
        self.assertEqual(self.definition(), spec["definition"])
        self.assertEqual(self.plist()["Label"], LABEL)


AT = "2026-11-17T06:00"
# 06:01 on that day in this Mac's zone, computed with the standard library, so the one-off tests run in any zone.
AFTER = int(__import__("datetime").datetime(2026, 11, 17, 6, 1, tzinfo=__import__("zoneinfo").ZoneInfo(TZ)).timestamp())


class OneOff(Scheduling):
    """K8: a one-off turns itself off when its time will not be tried again, and only the definition it was started from."""


    def make(self, profile="read-only", prompt="x"):
        self.cli_json("schedule", "--name", "nightly", prompt, "--at", AT, "--profile", profile)
        return json.loads(self.committed().splitlines()[1][len("# spec: "):])

    def job(self, spec, run_id, prompt, source="dispatcher", now=AFTER, event="workflow_dispatch"):
        d = self.root / "job" / run_id
        d.mkdir(parents=True, exist_ok=True)
        env = {"GITHUB_RUN_ID": run_id, "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": event, "GITHUB_REPOSITORY": REPO, "GITHUB_SERVER_URL": "https://github.com", "GITHUB_STEP_SUMMARY": str(d / "summary"), "GITHUB_OUTPUT": str(d / "output"), "GH_TOKEN": "job-token", "CLAUDE_SCHEDULE_MODE": "run", "CLAUDE_SCHEDULE_SOURCE": source, "CLAUDE_SCHEDULE_PROMPT": prompt, "CLAUDE_SKILL_TEST_NOW": str(now)}
        args = ["--name", "nightly", "--project", str(self.project), "--profile", spec["profile"], "--model", spec["model"], "--effort", spec["effort"], "--timeout", str(spec["timeout"]), "--at", spec["at"], "--timezone", spec["timezone"], "--workflow", "claude-nightly.yml", "--definition", spec["definition"]]
        run = self.cli("__scheduled", "run", *args, env=env, timeout=120)
        finish = self.cli("__scheduled", "finish", *args, env=env, timeout=120)
        return run, finish, (d / "summary").read_text() if (d / "summary").exists() else ""

    def wf_state(self):
        return self.repo()["workflows"].get("claude-nightly.yml")

    def test_a_completed_one_off_turns_itself_off(self):
        spec = self.make()
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual((run.returncode, finish.returncode), (0, 0), finish.stdout)
        self.assertEqual(self.wf_state(), "disabled_manually")
        self.assertIsNone(self.plist())
        self.assertIn("This one-off is done", summary)

    def test_a_failed_read_only_one_off_waits_for_its_retry(self):
        spec = self.make()
        self.job(spec, "1", "x [[fake:auth_fail]]")
        self.assertEqual(self.wf_state(), "active")
        self.assertIsNotNone(self.plist())
        run, finish, summary = self.job(spec, "2", "x", source="", event="schedule")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertEqual(self.wf_state(), "disabled_manually")
        self.assertIsNone(self.plist())

    def test_a_failed_writer_is_turned_off_at_once(self):
        spec = self.make(profile="write")
        self.job(spec, "1", "x [[fake:auth_fail]]")
        self.assertEqual(self.wf_state(), "disabled_manually")

    def test_a_one_off_long_past_is_skipped_and_turned_off(self):
        spec = self.make()
        run, finish, summary = self.job(spec, "1", "x", now=AFTER + 27 * 3600)
        self.assertIn("more than 26 hours ago", run.stdout)
        self.assertEqual(self.wf_state(), "disabled_manually")

    def test_a_definition_changed_meanwhile_is_left_alone(self):
        spec = self.make()
        self.make(prompt="x")  # the same content again: unchanged, same definition
        again = self.cli_json("schedule", "--name", "nightly", "--profile", "write")
        newer = json.loads(self.committed().splitlines()[1][len("# spec: "):])
        self.assertNotEqual(newer["definition"], spec["definition"])
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual(self.wf_state(), "active")
        self.assertIsNotNone(self.plist())
        self.assertIn("left the newer definition alone", summary)

    def test_unscheduled_meanwhile_is_left_alone(self):
        spec = self.make()
        self.cli_json("unschedule", "--name", "nightly")
        w = self.world()
        w["repos"][REPO]["workflows"]["claude-nightly.yml"] = "active"
        self.world(w)
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual(self.wf_state(), "active", "nothing of a removed definition is disabled")
        self.assertIn("left the newer definition alone", summary)

    def test_calling_again_after_the_time_needs_a_new_time(self):
        spec = self.make()
        self.job(spec, "1", "x")
        reply = self.cli_json("schedule", "--name", "nightly", "--model", "opus", expect=2, env={"CLAUDE_SKILL_TEST_NOW": str(AFTER + 3600)})
        self.assertIn("give a new --at", reply["error"])

    def test_a_failed_disable_names_the_command(self):
        spec = self.make()
        self.world(fail_disable=True)
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual(finish.returncode, 0)
        self.assertIn("gh workflow disable claude-nightly.yml --repo someone/project", summary)
        self.assertIsNone(self.plist(), "the dispatcher is removed even when the disable failed")
