"""`schedule`, `unschedule` and `schedule --list` through the CLI with a fake `gh` (answers shaped like captured real ones, over a simulated private repository) and a fake `launchctl` (real messages and exit codes), in a private HOME: what gets committed and installed, merging a second call into the first (K2), the halves of a failure (K12), the refusals, the one-off's end (K8) and two calls at once (S3); a name used as given for the file and the title, the names refused and why, a schedule 0.2.0 committed kept where it is, and names that would fall together on this Mac. The expected workflow is written by hand in the shape GitHub accepted (probe 11, stage PR ②; quoted titles, plan 261122 N1)."""

from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import sys
import shlex
import threading
import unicodedata
from pathlib import Path

from support.harness import ENTRY, FIXTURES, SUPPORT, Sandbox, engine, git
from support.names import ACCEPTED, NOT_RESERVED, REFUSED, RESERVED

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

    def committed(self, name="nightly", file=None):
        f = self.repo()["files"].get(f".github/workflows/{file or name + '.yml'}")
        return f["text"] if f else None

    def files(self):
        return sorted(k[len(".github/workflows/"):] for k in self.repo()["files"])

    def spec_of(self, name="nightly", file=None):
        return json.loads(self.committed(name, file).splitlines()[1][len("# spec: "):])

    def plant(self, file, text, state="active", **extra):
        """A workflow file on the default branch, as if committed from somewhere else; `state` None for one GitHub has not registered."""
        w = self.world()
        w["repos"][REPO]["files"][f".github/workflows/{file}"] = {"text": text, "sha": "abc", **extra}
        if state:
            w["repos"][REPO]["workflows"][file] = state
        self.world(w)

    def legacy(self, name="nightly"):
        """The workflow 0.2.0 committed as claude-NAME.yml for `schedule --name NAME 'Review yesterday…' --cron '0 3 * * *' --profile read-only` (a capture of its --dry-run, with this test's paths)."""
        text = (FIXTURES / "github" / "workflow-0.2.0.yml").read_text()
        for mark, value in (("{CLI}", json.dumps(str(ENTRY))[1:-1]), ("{PROJECT}", json.dumps(str(self.project))[1:-1]), ("{CLI_SH}", shlex.quote(str(ENTRY))), ("{PROJECT_SH}", shlex.quote(str(self.project))), ("{TZ}", TZ)):
            text = text.replace(mark, value)
        return text.replace("nightly", name)

    def named(self, name, *extra, expect=0, profile="write"):
        return self.cli_json("schedule", f"--name={name}", "x", "--cron", "0 3 * * *", "--profile", profile, *extra, expect=expect)

    def nothing_written(self):
        self.assertEqual([c["argv"] for c in self.gh_calls() if any(m in c["argv"] for m in ("PUT", "DELETE"))], [])
        self.assertEqual([c for c in self.lc_calls() if c[0] != "print"], [])
        self.assertFalse(self.runs_dir().exists(), "a refusal leaves no registry behind")

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

    def plant_plist(self, label=LABEL, repo=REPO, at=None, raw=None):
        """A dispatcher plist as `schedule` writes one, put at the path of label `at` (default: its own) — which is where a file system that ignores case, or a label two repositories share, puts another schedule's."""
        path = self.home / "Library" / "LaunchAgents" / f"{at or label}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        argv = ["/opt/homebrew/bin/gh", "workflow", "run", "x.yml", *(["--repo", repo] if repo else []), "--ref", "main", "-f", "source=dispatcher"]
        path.write_bytes(raw if raw is not None else plistlib.dumps({"Label": label, "ProgramArguments": argv}))
        return path, path.read_bytes()

    def plant_state(self, recorded, name="nightly"):
        d = self.runs_dir() / ".schedules" / name
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({"name": recorded, "last_slot": None, "slots": {}, "jobs": {}}))
        return d / "state.json"

    def schedule(self, *args, expect=0, input=None):
        return self.cli_json("schedule", "--name", "nightly", *args, expect=expect, input=input)

    def new(self, *extra, prompt="Review yesterday's commits and report what looks risky.", **kw):
        return self.schedule(prompt, "--cron", "0 3 * * *", "--profile", "read-only", *extra, **kw)

    def expected_workflow(self, definition, prompt="Review yesterday's commits and report what looks risky.", cron="0 3 * * *", profile="read-only"):
        spec = {"at": None, "cli": str(ENTRY), "cron": cron, "definition": definition, "effort": "high", "model": "sonnet", "name": "nightly", "profile": profile, "project": str(self.project), "prompt": prompt, "runs_on": ["self-hosted"], "schema": None, "timeout": 3600, "timezone": TZ, "worktree": False}
        steps = f"--name nightly --project {shlex.quote(str(self.project))} --profile {profile} --model sonnet --effort high --timeout 3600 --cron '{cron}' --timezone {TZ} --workflow nightly.yml --definition {definition}"

        def run(step):
            # The step's command: shell words, written as a YAML double-quoted (JSON) string.
            return json.dumps(f"uv run {shlex.quote(str(ENTRY))} __scheduled {step} {steps}", ensure_ascii=False)

        env = f"""          CLAUDE_SCHEDULE_MODE: ${{{{ inputs.mode }}}}
          CLAUDE_SCHEDULE_SOURCE: ${{{{ inputs.source }}}}
          CLAUDE_SCHEDULE_PROMPT: |2-
            {prompt}"""
        return f"""# Written by the claude skill's `schedule` command. Run it again with the same --name to change it; `unschedule` removes it.
# spec: {json.dumps(spec, ensure_ascii=False, sort_keys=True)}
name: "nightly"
run-name: "nightly · ${{{{ inputs.mode == 'check' && 'check' || inputs.source || github.event_name }}}}"
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
  group: "claude-nightly"
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
        self.assertEqual(plist["ProgramArguments"][1:], ["workflow", "run", "nightly.yml", "--repo", REPO, "--ref", "main", "-f", "source=dispatcher"])
        self.assertTrue(plist["ProgramArguments"][0].endswith("fake_gh/gh"))
        self.assertEqual(plist["StartCalendarInterval"], [{"Minute": 0, "Hour": 3}])
        self.assertEqual(plist["StandardOutPath"], str(self.home / "Library" / "Logs" / "claude-schedule" / "someone-project.nightly.log"))
        self.assertIn(["bootstrap", f"gui/{os.getuid()}", str(self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist")], self.lc_calls())
        self.assertEqual(reply["workflow"]["status"], "committed")
        self.assertEqual(reply["dispatcher"]["status"], "installed")
        self.assertEqual(reply["fires"]["next"][0], f"2026-11-18 03:00 {'KST' if TZ == 'Asia/Seoul' else reply['fires']['next'][0].split()[-1]}")
        self.assertEqual(reply["next"]["command"], f"gh workflow run nightly.yml --repo {REPO} -f mode=check")
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
        w["repos"][REPO]["workflows"]["nightly.yml"] = "disabled_manually"
        self.world(w)
        reply = self.schedule("--profile", "write")
        self.assertTrue(reply["workflow"]["was_disabled"])
        self.assertEqual(self.repo()["workflows"]["nightly.yml"], "active")

    def test_dry_run_writes_nothing(self):
        reply = self.new("--dry-run")
        self.assertIn('name: "nightly"', reply["workflow_text"])
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

    def test_a_branch_name_reaches_github_whole(self):
        # In a URL `&` ends a query value and `#` the whole path: read raw, the second call would not find what the first committed.
        w = self.world()
        w["repos"][REPO]["default_branch"] = "release&1#x"
        self.world(w)
        self.assertEqual(self.new()["workflow"]["status"], "committed")
        self.assertEqual(self.schedule()["workflow"]["status"], "unchanged")
        reads = [c["argv"][-1] for c in self.gh_calls() if c["argv"][:3] == ["api", "-X", "GET"] and "/contents/" in c["argv"][-1]]
        self.assertTrue(reads and all(r.endswith("?ref=release%261%23x") for r in reads), reads)

    def test_the_repository_is_named_as_github_spells_it(self):
        git(self.project, "remote", "set-url", "origin", "https://github.com/Someone/Project.git")
        reply = self.new()
        self.assertEqual(reply["repo"], REPO)
        self.assertEqual(reply["dispatcher"]["label"], LABEL)
        self.assertIsNotNone(self.plist())

    def test_the_state_of_a_workflow_on_a_later_page_is_read(self):
        self.new()
        w = self.world()
        for n in range(150):
            w["repos"][REPO]["workflows"][f"build-{n:03d}.yml"] = "active"  # sorted before the schedule's file, which lands on page 2
        w["repos"][REPO]["workflows"]["nightly.yml"] = "disabled_manually"
        self.world(w)
        out = self.cli_json("schedule", "--list")
        self.assertEqual([(r["name"], r["state"]) for r in out["schedules"]], [("nightly", "disabled")])
        self.assertEqual(out["orphans"], [])

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
            (("--name", "", "x", "--cron", "0 3 * * *", "--profile", "read-only"), "--name"),
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
        w["repos"][REPO]["files"][".github/workflows/mine.yml"] = {"text": "name: mine\non: push\n", "sha": "abc"}
        self.world(w)
        reply = self.cli_json("schedule", "--name", "mine", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1)
        self.assertIn(".github/workflows/mine.yml exists and is not this schedule", reply["error"])

    def test_a_refusal_writes_nothing_here_either(self):
        self.cli_json("schedule", "--name", "nightly", "--cron", "0 3 * * *", "--profile", "read-only", expect=2)
        self.assertFalse(self.runs_dir().exists(), "a refusal leaves no registry behind")

    def test_a_network_failure_is_not_sent_to_a_pull_request(self):
        self.world(offline=True)
        reply = self.new(expect=1)
        self.assertIn("error connecting", reply["error"])
        self.assertNotIn("pull request", reply.get("instead") or "")
        self.assertNotIn("nothing was written", reply.get("instead") or "", "a request that got no answer may still have been committed")

    def test_a_lost_answer_clears_this_macs_definition(self):
        self.new()
        self.assertIsNotNone(self.definition())
        self.world(offline=True)
        self.new("--profile", "write", expect=1)
        self.assertIsNone(self.definition(), "a one-off job started from the old definition must not match whatever GitHub may now hold")

    def test_inside_a_worker(self):
        reply = self.cli_json("schedule", "--name", "nightly", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1, env={"CLAUDE_SKILL_RUN": "r1"})
        self.assertIn("inside worker run", reply["error"])


class Unschedule(Scheduling):
    def test_a_workflow_with_a_spec_line_of_its_own_is_left_alone(self):
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/mine.yml"] = {"text": "# spec: {}\nname: mine\non: push\n", "sha": "abc"}
        self.world(w)
        self.assertIn("is not this schedule", self.cli_json("unschedule", "--name", "mine", expect=1)["error"])
        self.assertIn("is not this schedule", self.cli_json("schedule", "--name", "mine", "x", "--cron", "0 3 * * *", "--profile", "read-only", expect=1)["error"])

    def test_a_file_this_skill_did_not_write_is_left_alone(self):
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/code-review.yml"] = {"text": "name: review\non: pull_request\n", "sha": "abc"}
        self.world(w)
        reply = self.cli_json("unschedule", "--name", "code-review", expect=1)
        self.assertIn(".github/workflows/code-review.yml exists and is not this schedule", reply["error"])
        self.assertIn(".github/workflows/code-review.yml", self.repo()["files"])

    def test_a_hand_written_file_with_the_old_prefix_is_not_in_the_way(self):
        # claude-NAME.yml was the skill's own file name once; one that is not a schedule is simply another workflow now.
        hand = "name: review\non: pull_request\n"
        self.plant("claude-code-review.yml", hand)
        gone = self.cli_json("unschedule", "--name", "code-review")
        self.assertEqual(gone["workflow"], {"status": "absent", "path": ".github/workflows/code-review.yml"})
        reply = self.named("code-review")
        self.assertEqual(reply["workflow"]["path"], ".github/workflows/code-review.yml")
        self.assertEqual(self.files(), ["claude-code-review.yml", "code-review.yml"])
        self.assertEqual(self.committed(file="claude-code-review.yml"), hand)

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


class Names(Scheduling):
    """`--name` as given: the workflow file, the title in Actions, this Mac's dispatcher label and state directory."""

    def test_a_name_is_the_file_and_the_title_as_given(self):
        name = "261128_SS_외국인순매수"
        reply = self.named(name, "--worktree")
        self.assertEqual((reply["name"], reply["workflow"]["status"], reply["workflow"]["path"]), (name, "committed", ".github/workflows/261128_SS_외국인순매수.yml"))
        lines = self.committed(name).splitlines()
        self.assertIn('name: "261128_SS_외국인순매수"', lines)
        self.assertIn("run-name: \"261128_SS_외국인순매수 · ${{ inputs.mode == 'check' && 'check' || inputs.source || github.event_name }}\"", lines)
        self.assertEqual(self.repo()["workflows"], {"261128_SS_외국인순매수.yml": "active"})
        plist = self.plist("claude-schedule.someone-project.261128_SS_외국인순매수")
        self.assertEqual(plist["ProgramArguments"][1:4], ["workflow", "run", "261128_SS_외국인순매수.yml"])
        self.assertEqual(plist["StandardOutPath"], str(self.home / "Library" / "Logs" / "claude-schedule" / "someone-project.261128_SS_외국인순매수.log"))
        self.assertEqual(self.definition(name), self.spec_of(name)["definition"])
        self.assertEqual([(r["name"], r["file"], r["dispatcher"]) for r in self.cli_json("schedule", "--list")["schedules"]], [(name, "261128_SS_외국인순매수.yml", "loaded")])
        gone = self.cli_json("unschedule", "--name", name)
        self.assertEqual((gone["dispatcher"]["status"], gone["workflow"]["status"]), ("removed", "deleted"))
        self.assertEqual(self.files(), [])

    def test_names_taken_as_given(self):
        for name in ACCEPTED:
            with self.subTest(name=name):
                reply = self.named(name, "--dry-run")
                self.assertEqual((reply["name"], reply["workflow_path"]), (name, f".github/workflows/{name}.yml"))

    def test_names_refused_with_the_reason(self):
        for name, word in REFUSED:
            with self.subTest(name=name):
                self.assertIn(word, self.named(name, expect=2)["error"])
                self.assertIn(word, self.named(name, "--dry-run", expect=2)["error"])
                self.assertIn(word, self.cli_json("unschedule", f"--name={name}", expect=2)["error"])
        self.assertEqual(self.files(), [])
        self.nothing_written()

    def test_a_decomposed_name_is_committed_composed(self):
        # 한글 as conjoining jamo (NFD) and as syllables (NFC): GitHub keeps the two as different paths, so one form is chosen before anything is written.
        nfd, nfc = "\u1112\u1161\u11ab\u1100\u1173\u11af", "\ud55c\uae00"
        self.assertEqual(unicodedata.normalize("NFC", nfd), nfc)
        reply = self.named(nfd)
        self.assertEqual(reply["name"], nfc)
        self.assertEqual(self.files(), [nfc + ".yml"])
        self.assertEqual(self.spec_of(nfc)["name"], nfc)
        self.assertEqual(self.named(nfd)["workflow"]["status"], "unchanged")
        self.assertEqual(self.cli_json("unschedule", f"--name={nfd}")["workflow"]["status"], "deleted")

    def test_an_awkward_name_reaches_github_and_the_reader_whole(self):
        name = "a#b%c d"
        reply = self.named(name)
        self.assertEqual(self.files(), ["a#b%c d.yml"])
        self.assertEqual(reply["next"]["command"], f"gh workflow run 'a#b%c d.yml' --repo {REPO} -f mode=check")
        self.assertEqual(self.named(name)["workflow"]["status"], "unchanged")
        paths = [c["argv"][-1] for c in self.gh_calls() if c["argv"][:1] == ["api"]]
        self.assertIn("repos/someone/project/contents/.github/workflows/a%23b%25c%20d.yml?ref=main", paths)
        self.assertIn("repos/someone/project/actions/workflows/a%23b%25c%20d.yml", paths)
        self.assertEqual(self.cli_json("unschedule", "--name", name)["workflow"]["status"], "deleted")
        self.assertEqual(self.files(), [])

    def test_a_stale_path_names_the_call_that_refreshes_it(self):
        self.named("weekly report")
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/weekly report.yml"]["text"] = self.committed("weekly report").replace(str(ENTRY), "/nowhere/cli.py")
        self.world(w)
        (row,) = self.cli_json("schedule", "--list")["schedules"]
        self.assertEqual(row["fix"], "schedule --name 'weekly report'")


class Legacy(Scheduling):
    """A schedule 0.2.0 committed lives in claude-NAME.yml under the title `claude · NAME`. It stays there: to GitHub a renamed file is another workflow whose runs stay behind, and whatever refers to the title would stop matching."""

    def test_calling_again_changes_the_old_file_in_place(self):
        self.plant("claude-nightly.yml", self.legacy())
        reply = self.schedule("--cron", "30 4 * * *")
        self.assertEqual((reply["workflow"]["status"], reply["workflow"]["path"]), ("committed", ".github/workflows/claude-nightly.yml"))
        self.assertEqual(self.files(), ["claude-nightly.yml"], "no file of the new shape appears")
        text = self.committed(file="claude-nightly.yml")
        self.assertIn('\nname: "claude · nightly"\n', text)
        self.assertEqual(text.count("--workflow claude-nightly.yml --definition"), 2)
        spec = self.spec_of(file="claude-nightly.yml")
        self.assertEqual((spec["cron"], spec["prompt"], spec["profile"]), ("30 4 * * *", "Review yesterday's commits and report what looks risky.", "read-only"))
        self.assertEqual(self.plist()["ProgramArguments"][1:4], ["workflow", "run", "claude-nightly.yml"])
        self.assertEqual(reply["next"]["command"], f"gh workflow run claude-nightly.yml --repo {REPO} -f mode=check")

    def test_the_first_call_commits_once_even_with_nothing_changed(self):
        # Only the title's quoting differs from what 0.2.0 wrote; after that the file is stable.
        self.plant("claude-nightly.yml", self.legacy())
        self.assertEqual(self.schedule()["workflow"]["status"], "committed")
        self.assertEqual(self.schedule()["workflow"]["status"], "unchanged")
        self.assertEqual(self.files(), ["claude-nightly.yml"])

    def test_unschedule_removes_the_old_file(self):
        self.plant("claude-nightly.yml", self.legacy())
        self.plant_plist()
        reply = self.cli_json("unschedule", "--name", "nightly")
        self.assertEqual((reply["workflow"], reply["dispatcher"]["status"]), ({"status": "deleted", "path": ".github/workflows/claude-nightly.yml", "commit": reply["workflow"]["commit"]}, "removed"))
        self.assertEqual(self.files(), [])

    def test_the_old_file_is_the_schedule_beside_a_hand_written_file_of_the_new_name(self):
        hand = "name: foo\non: push\n"
        self.plant("claude-foo.yml", self.legacy("foo"))
        self.plant("foo.yml", hand)
        reply = self.cli_json("schedule", "--name", "foo", "--cron", "30 4 * * *")
        self.assertEqual(reply["workflow"]["path"], ".github/workflows/claude-foo.yml")
        self.assertEqual(self.committed(file="foo.yml"), hand)

    def test_a_new_name_that_is_an_old_schedules_file_is_refused(self):
        self.plant("claude-foo.yml", self.legacy("foo"))
        reply = self.named("claude-foo", expect=1)
        self.assertIn(".github/workflows/claude-foo.yml exists and is not this schedule", reply["error"])
        self.assertEqual(self.spec_of(file="claude-foo.yml")["name"], "foo")

    def test_an_old_schedule_whose_name_starts_with_the_prefix(self):
        self.plant("claude-foo.yml", self.legacy("foo"))
        self.plant("claude-claude-foo.yml", self.legacy("claude-foo"))
        reply = self.cli_json("schedule", "--name", "claude-foo", "--cron", "30 4 * * *")
        self.assertEqual(reply["workflow"]["path"], ".github/workflows/claude-claude-foo.yml")
        self.assertEqual(self.spec_of(file="claude-foo.yml")["cron"], "0 3 * * *", "schedule foo is untouched")

    def test_two_files_that_both_say_they_are_the_schedule(self):
        self.plant("claude-foo.yml", self.legacy("foo"))
        self.plant("foo.yml", self.legacy("foo"))
        for call in (("schedule", "--name", "foo", "--cron", "30 4 * * *"), ("unschedule", "--name", "foo")):
            reply = self.cli_json(*call, expect=1)
            self.assertIn(".github/workflows/foo.yml", reply["error"])
            self.assertIn(".github/workflows/claude-foo.yml", reply["error"])
        self.assertEqual(self.files(), ["claude-foo.yml", "foo.yml"])

    def test_a_name_0_2_0_could_not_have_taken_has_no_old_file(self):
        # 0.2.0 took no capital letter, so claude-Report.yml is not where schedule Report would be looked for: it is a schedule of that name under some other file, which a new one must not double.
        before = self.legacy("Report")
        self.plant("claude-Report.yml", before)
        reply = self.named("Report", expect=1)
        self.assertIn("schedule Report (.github/workflows/claude-Report.yml) has this name under another file", reply["error"])
        self.assertEqual(self.committed(file="claude-Report.yml"), before)
        self.assertEqual(self.files(), ["claude-Report.yml"])


class Overlaps(Scheduling):
    """A new schedule must not fall together with what is already in the workflow directory on a file system that ignores letter case and Unicode form — this Mac's: the two would be one file in a checkout, and one state directory, lock and dispatcher plist here. Nor may its file be one Windows cannot check out."""

    def refused(self, name, *says):
        for extra in ((), ("--dry-run",)):
            reply = self.named(name, *extra, expect=1)
            for word in says:
                self.assertIn(word, reply["error"])
        self.nothing_written()
        self.assertIsNone(self.plist(f"claude-schedule.someone-project.{name}"))

    def test_a_file_that_differs_only_by_case(self):
        self.plant("Weekly.yml", "name: hand\non: push\n")
        self.refused("weekly", "Weekly.yml")

    def test_a_file_that_differs_only_by_unicode_form(self):
        self.plant("\u1112\u1161\u11ab\u1100\u1173\u11af.yml", "name: hand\non: push\n")
        self.refused("\ud55c\uae00", "\u1112\u1161\u11ab\u1100\u1173\u11af.yml")

    def test_a_directory_of_that_name(self):
        self.plant("Weekly.yml/inner.yml", "x\n", state=None)
        self.refused("weekly", "Weekly.yml")

    def test_another_schedule_whose_name_differs_only_by_case(self):
        self.plant("claude-foo.yml", self.legacy("foo"))
        self.refused("Foo", "schedule foo", "claude-foo.yml")

    def test_the_same_name_under_another_file(self):
        self.plant("moved.yml", self.legacy("Report"))
        self.refused("Report", "schedule Report", "moved.yml")

    def test_names_windows_reserves(self):
        for name in RESERVED:
            with self.subTest(name=name):
                self.setUp()
                self.refused(name, "Windows")
        for name in NOT_RESERVED:
            with self.subTest(name=name):
                self.assertEqual(self.named(name, "--dry-run")["workflow_path"], f".github/workflows/{name}.yml")

    def test_an_old_schedule_keeps_a_name_windows_reserves(self):
        self.plant("claude-aux.yml", self.legacy("aux"))
        reply = self.cli_json("schedule", "--name", "aux", "--cron", "30 4 * * *")
        self.assertEqual((reply["workflow"]["status"], reply["workflow"]["path"]), ("committed", ".github/workflows/claude-aux.yml"))


class Ownership(Scheduling):
    """This Mac's dispatcher plist and state directory are touched only when they are this schedule's: a label joins owner, repository and name without marking where each ends, and the file system ignores letter case and Unicode form, so another schedule's can sit at the same path."""

    def test_schedule_refuses_a_dispatcher_path_another_schedule_holds(self):
        for what, plant, says in (("another repository's", {"repo": "some/one-project"}, "some/one-project"), ("another label's", {"label": LABEL.upper()}, LABEL.upper()), ("names no repository", {"repo": None}, ".plist"), ("unreadable", {"raw": b"not a plist"}, ".plist")):
            for extra in ((), ("--dry-run",)):
                with self.subTest(what=what, extra=extra):
                    self.setUp()
                    path, before = self.plant_plist(at=LABEL, **plant)
                    reply = self.new(*extra, expect=1)
                    self.assertIn(says, reply["error"])
                    self.assertIsNone(self.committed())
                    self.assertEqual(path.read_bytes(), before)
                    self.assertFalse(self.runs_dir().exists(), "a refusal leaves no registry behind")

    def test_schedule_refuses_a_state_directory_another_schedule_holds(self):
        state = self.plant_state("NIGHTLY")
        before = state.read_text()
        reply = self.new(expect=1)
        self.assertIn("NIGHTLY", reply["error"])
        self.assertIsNone(self.committed())
        self.assertIsNone(self.plist())
        self.assertEqual(state.read_text(), before)

    def test_unschedule_removes_nothing_of_another_schedule(self):
        path, before = self.plant_plist(repo="some/one-project")
        reply = self.cli_json("unschedule", "--name", "nightly", expect=1)
        self.assertIn("some/one-project", reply["error"])
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        state = self.plant_state("NIGHTLY")
        reply = self.cli_json("unschedule", "--name", "nightly", expect=1)
        self.assertIn("NIGHTLY", reply["error"])
        self.assertTrue(state.exists())

    def test_unschedule_of_a_name_that_differs_only_by_case_leaves_the_other_schedule(self):
        probe = self.root / "Case_Probe"
        probe.mkdir()
        if not (self.root / "case_probe").exists():
            self.skipTest("the temporary directory is on a file system that tells letter case apart, where the two names do not share a path")
        self.named("foo")
        plist = self.home / "Library" / "LaunchAgents" / "claude-schedule.someone-project.foo.plist"
        before = plist.read_bytes()
        reply = self.cli_json("unschedule", "--name", "Foo", expect=1)
        self.assertIn("claude-schedule.someone-project.foo", reply["error"])
        self.assertEqual(plist.read_bytes(), before)
        self.assertEqual(self.definition("foo"), self.spec_of("foo")["definition"])
        self.assertEqual(self.files(), ["foo.yml"])

    def test_unschedule_removes_its_own_leftovers(self):
        path, _ = self.plant_plist()
        state = self.plant_state("nightly")
        reply = self.cli_json("unschedule", "--name", "nightly")
        self.assertEqual((reply["dispatcher"]["status"], reply["workflow"]["status"]), ("removed", "absent"))
        self.assertFalse(path.exists())
        self.assertFalse(state.exists())

    def test_unschedule_of_a_committed_schedule_leaves_what_is_not_its_own(self):
        self.new()
        path, before = self.plant_plist(repo="some/one-project")
        state = self.runs_dir() / ".schedules" / "nightly" / "state.json"
        state.write_text(json.dumps({**json.loads(state.read_text()), "name": "NIGHTLY"}))
        reply = self.cli_json("unschedule", "--name", "nightly")
        self.assertEqual((reply["workflow"]["status"], reply["dispatcher"]["status"]), ("deleted", "absent"))
        self.assertIn("some/one-project", reply["note"])
        self.assertIn("NIGHTLY", reply["note"])
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(state.exists())


class Listing(Scheduling):
    HEADER = "# Written by the claude skill's `schedule` command. Run it again with the same --name to change it; `unschedule` removes it."

    def ours(self, name):
        spec = {"at": None, "cli": str(ENTRY), "cron": "0 9 * * 1", "definition": "3f9a1c2e", "effort": "high", "model": "sonnet", "name": name, "profile": "write", "project": str(self.project), "prompt": "x", "runs_on": ["self-hosted"], "schema": None, "timeout": 3600, "timezone": TZ, "worktree": False}
        return f"{self.HEADER}\n# spec: {json.dumps(spec, ensure_ascii=False, sort_keys=True)}\nname: anything\non: workflow_dispatch\n"

    def test_schedules_are_found_by_their_header_whatever_the_file_is_called(self):
        self.plant("claude-nightly.yml", self.ours("nightly"))  # as 0.2.0 named files
        self.plant("261128_SS_외국인순매수.yml", self.ours("261128_SS_외국인순매수"), state="disabled_manually")
        self.plant("weekly.yaml", self.ours("weekly"), state=None)
        self.plant("b-second.yml", self.ours("same name"))
        self.plant("a-first.yml", self.ours("same name"))
        self.plant("ci.yml", "name: ci\non: push\n")
        self.plant("claude-code-review.yml", "name: review\non: pull_request\n")
        self.plant("spec-no-header.yml", "# spec: {\"name\": \"x\"}\nname: x\n")
        self.plant("spec-not-an-object.yml", f"{self.HEADER}\n# spec: [1]\n")
        self.plant("name-is-a-list.yml", f"{self.HEADER}\n# spec: {{\"name\": [\"x\"]}}\n")
        self.plant("sub/inner.yml", self.ours("inner"), state=None)
        out = self.cli_json("schedule", "--list")
        self.assertEqual([(r["name"], r["file"], r["state"]) for r in out["schedules"]], [
            ("261128_SS_외국인순매수", "261128_SS_외국인순매수.yml", "disabled"),
            ("nightly", "claude-nightly.yml", "active"),
            ("same name", "a-first.yml", "active"),
            ("same name", "b-second.yml", "active"),
            ("weekly", "weekly.yaml", "unknown"),
        ])
        self.assertEqual(list(out["schedules"][0])[:2], ["name", "file"])
        self.assertEqual(len([c for c in self.gh_calls() if c["argv"][:2] == ["api", "graphql"]]), 1, "one call brings every file's name and body")

    def test_a_body_the_listing_did_not_bring_is_read_on_its_own(self):
        self.plant("nightly.yml", self.ours("nightly"), graphql="none")
        self.assertEqual([r["name"] for r in self.cli_json("schedule", "--list")["schedules"]], ["nightly"])

    def test_list(self):
        self.new()
        self.cli_json("schedule", "--name", "weekly", "y", "--cron", "0 9 * * 1", "--profile", "write")
        w = self.world()
        w["repos"][REPO]["workflows"]["weekly.yml"] = "disabled_manually"
        self.world(w)
        self.plant_plist(label="claude-schedule.someone-project.gone")
        # Not this repository's orphans: a label two repositories share, one a case-blind file system put under another's name, and plists that do not say.
        self.plant_plist(label="claude-schedule.someone-project.theirs", repo="some/one-project")
        self.plant_plist(label="claude-schedule.someone-project.CASE", at="claude-schedule.someone-project.case")
        self.plant_plist(label="claude-schedule.someone-project.norepo", repo=None)
        self.plant_plist(label="claude-schedule.someone-project.garbage", raw=b"not a plist")
        text = self.committed().replace(str(ENTRY), "/nowhere/cli.py")
        w = self.world()
        w["repos"][REPO]["files"][".github/workflows/nightly.yml"]["text"] = text
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

    def job(self, spec, run_id, prompt, source="dispatcher", now=AFTER, event="workflow_dispatch", workflow="nightly.yml"):
        d = self.root / "job" / run_id
        d.mkdir(parents=True, exist_ok=True)
        env = {"GITHUB_RUN_ID": run_id, "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": event, "GITHUB_REPOSITORY": REPO, "GITHUB_SERVER_URL": "https://github.com", "GITHUB_STEP_SUMMARY": str(d / "summary"), "GITHUB_OUTPUT": str(d / "output"), "GH_TOKEN": "job-token", "CLAUDE_SCHEDULE_MODE": "run", "CLAUDE_SCHEDULE_SOURCE": source, "CLAUDE_SCHEDULE_PROMPT": prompt, "CLAUDE_SKILL_TEST_NOW": str(now)}
        args = ["--name", "nightly", "--project", str(self.project), "--profile", spec["profile"], "--model", spec["model"], "--effort", spec["effort"], "--timeout", str(spec["timeout"]), "--at", spec["at"], "--timezone", spec["timezone"], *(["--workflow", workflow] if workflow else []), "--definition", spec["definition"]]
        run = self.cli("__scheduled", "run", *args, env=env, timeout=120)
        finish = self.cli("__scheduled", "finish", *args, env=env, timeout=120)
        return run, finish, (d / "summary").read_text() if (d / "summary").exists() else ""

    def wf_state(self):
        return self.repo()["workflows"].get("nightly.yml")

    def test_a_completed_one_off_turns_itself_off(self):
        spec = self.make()
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual((run.returncode, finish.returncode), (0, 0), finish.stdout)
        self.assertEqual(self.wf_state(), "disabled_manually")
        self.assertIsNone(self.plist())
        self.assertIn("This one-off is done", summary)

    def test_a_one_off_turns_off_the_workflow_file_its_step_names(self):
        # A step 0.2.0 wrote names claude-NAME.yml and a later one NAME.yml; each job turns off its own file, and a step naming none is 0.2.0's.
        for given, off in (("nightly.yml", "nightly.yml"), ("claude-nightly.yml", "claude-nightly.yml"), (None, "claude-nightly.yml")):
            with self.subTest(workflow=given):
                self.setUp()
                spec = self.make()
                w = self.world()
                w["repos"][REPO]["workflows"] = {"claude-nightly.yml": "active", "nightly.yml": "active"}
                self.world(w)
                run, finish, summary = self.job(spec, "1", "x", workflow=given)
                self.assertEqual((run.returncode, finish.returncode), (0, 0), finish.stdout)
                self.assertEqual({f for f, state in self.repo()["workflows"].items() if state != "active"}, {off})
                self.assertIn(f"gh workflow enable {off} --repo someone/project", summary)

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
        w["repos"][REPO]["workflows"]["nightly.yml"] = "active"
        self.world(w)
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual(self.wf_state(), "active", "nothing of a removed definition is disabled")
        self.assertIn("left the newer definition alone", summary)

    def test_a_one_off_leaves_a_dispatcher_that_is_not_its_own(self):
        spec = self.make()
        path, before = self.plant_plist(repo="some/one-project")
        run, finish, summary = self.job(spec, "1", "x")
        self.assertEqual(finish.returncode, 0, finish.stdout)
        self.assertEqual(self.wf_state(), "disabled_manually", "its own workflow is still turned off")
        self.assertEqual(path.read_bytes(), before)
        warning = summary.split("[!WARNING]", 1)[1].split("\n\n", 1)[0]
        self.assertIn("some/one-project", warning)

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
        self.assertIn("gh workflow disable nightly.yml --repo someone/project", summary)
        self.assertIsNone(self.plist(), "the dispatcher is removed even when the disable failed")
