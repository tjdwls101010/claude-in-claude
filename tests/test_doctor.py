"""`doctor` through the CLI with the fake claude, and the usage-limit and retry lines a run's log carries. Expected limits come from tests/support/fixtures/usage.jsonl, a real `claude -p /usage` capture."""

from __future__ import annotations

import json

from support.harness import FIXTURES, Sandbox, git


def fixture_limits():
    for line in (FIXTURES / "usage.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e.get("usage_report"):
            return [(x["kind"], x["percent"]) for x in e["usage_report"]["rate_limits"]["limits"]]


class Doctor(Sandbox):
    def doctor(self, expect=0, **kw):
        return self.cli_json("doctor", expect=expect, timeout=120, **kw)

    def test_healthy(self):
        d = self.doctor()
        self.assertTrue(d["ok"])
        self.assertEqual(d["blockers"], [])
        self.assertEqual(d["claude"]["version"], "2.1.314")
        self.assertEqual(d["claude"]["floor"], "2.1.314")
        self.assertEqual(d["auth"], {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max", "apiProvider": None})
        self.assertNotIn("email", json.dumps(d))
        self.assertEqual([(x["kind"], x["percent"]) for x in d["quota"]["limits"]], fixture_limits())
        self.assertEqual(d["registry"]["path"], str(self.project / ".claude-runs"))
        self.assertTrue(d["invocation"].startswith('uv run "'))
        (usage,) = [c for c in self.fake_calls() if "-p" in c["argv"]]
        self.assertEqual(usage["argv"][-1], "/usage")
        self.assertIn("--safe-mode", usage["argv"], "no hooks or plugins for a limits check")
        self.assertIn("--no-session-persistence", usage["argv"])
        self.assertNotIn("--input-format", usage["argv"])

    def test_not_logged_in_is_a_blocker(self):
        d = self.doctor(expect=3, env={"FAKE_CLAUDE_AUTH": json.dumps({"loggedIn": False})})
        self.assertFalse(d["ok"])
        self.assertTrue(any("not logged in" in b for b in d["blockers"]))

    def test_no_claude_is_a_blocker(self):
        d = self.doctor(expect=3, env={"PATH": "/usr/bin:/bin"})
        self.assertTrue(any("not on PATH" in b for b in d["blockers"]))

    def test_quota_failure_is_a_warning(self):
        d = self.doctor(env={"FAKE_CLAUDE_USAGE": "fail"})
        self.assertTrue(d["ok"])
        self.assertIn("error", d["quota"])
        self.assertTrue(any("usage limits" in w for w in d["warnings"]))

    def test_widening_settings_are_warned(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"sandbox": {"excludedCommands": ["docker"]}}))
        d = self.doctor()
        self.assertTrue(any("excludedCommands" in w for w in d["warnings"]))
        self.assertEqual([x["setting"] for x in d["profile_exceptions"]["read-only"]], ["sandbox.excludedCommands"])

    def test_registry_that_does_not_exist_yet(self):
        d = self.cli_json("doctor", "--runs-dir", str(self.root / "nope" / "a" / "b"), timeout=120)
        self.assertTrue(d["ok"], d["blockers"])
        self.assertTrue(d["registry"]["writable"])

    def test_worktrees_are_credited_to_their_own_group(self):
        for name in ("fix", "fix-db"):
            reply = self.cli_json("batch", "--group", name, "--worktree", "--task", "x", timeout=120)
            self.wait_state(reply["runs"][0]["run_id"])
        for seed in ("0", "2", "3"):
            d = self.doctor(env={"PYTHONHASHSEED": seed})
            self.assertEqual(sorted((w["path"].rsplit("/", 1)[1], w["group"]) for w in d["registry"]["worktrees"]), [("fix-1", "fix"), ("fix-db-1", "fix-db")], seed)

    def test_registry_live_runs_and_worktrees(self):
        live = self.start("x [[fake:sleep:30]]")
        git(self.project, "worktree", "add", "-q", "-b", "worktree-old-1", str(self.project / ".claude" / "worktrees" / "old-1"))
        d = self.doctor()
        self.assertEqual(d["registry"]["live_runs"], [live["run_id"]])
        self.assertEqual([(w["path"].rsplit("/", 1)[1], w["group"]) for w in d["registry"]["worktrees"]], [("old-1", None)])
        self.cli_json("stop", "--run", live["run_id"])


class OldClaude(Sandbox):
    fake_version = "2.1.300"

    def test_below_the_floor_is_a_blocker(self):
        d = self.cli_json("doctor", expect=3)
        self.assertTrue(any("2.1.314" in b for b in d["blockers"]))


class LimitsInLogs(Sandbox):
    def test_retry_and_rate_limit_lines(self):
        reply = self.start("x [[fake:retry:2]] [[fake:silent:0.2]] [[fake:ratelimit_late:allowed_warning]]")
        self.wait_state(reply["run_id"])
        lines = self.cli("log", "--run", reply["run_id"]).stdout.splitlines()
        self.assertIn("retry attempt=1/10 error=overloaded status=529", lines)
        self.assertIn("retry attempt=2/10 error=overloaded status=529", lines)
        self.assertEqual([l for l in lines if l.startswith("ratelimit ")], ["ratelimit allowed 5h=2% 7d=42%", "ratelimit allowed_warning 5h=2% 7d=42%"])
        self.assertEqual(self.status(reply["run_id"])["rate_limit"]["status"], "allowed_warning")


class ScheduleReadiness(Sandbox):
    """doctor's `schedule` section, with the fake gh's simulated repository and a runner service under the private HOME: no runner, a runner whose service runs in its own security session, and a ready one. Never a blocker."""

    def setUp(self):
        super().setUp()
        import os
        import plistlib

        self.plistlib = plistlib
        git(self.project, "remote", "add", "origin", "https://github.com/someone/project.git")
        (self.root / "fake-gh").mkdir(exist_ok=True)
        self.world = self.root / "fake-gh" / "world.json"
        self.world.write_text(json.dumps({"auth": "ok", "repos": {"someone/project": {"private": True, "default_branch": "main", "runners": []}}}))
        self.bin = self.root / "runner-bin"
        self.bin.mkdir()
        for tool in ("uv", "claude"):
            (self.bin / tool).write_text("#!/bin/sh\n")
            os.chmod(self.bin / tool, 0o755)

    def runner(self, session_create, status="online"):
        w = json.loads(self.world.read_text())
        w["repos"]["someone/project"]["runners"] = [{"name": "mac", "status": status}]
        self.world.write_text(json.dumps(w))
        rdir = self.root / "actions-runner"
        rdir.mkdir(exist_ok=True)
        (rdir / ".path").write_text(f"{self.bin}:/usr/bin:/bin")
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist = {"Label": "actions.runner.someone-project.mac", "WorkingDirectory": str(rdir)}
        if session_create:
            plist["SessionCreate"] = True
        (agents / "actions.runner.someone-project.mac.plist").write_bytes(self.plistlib.dumps(plist))

    def schedule(self):
        d = self.cli_json("doctor", timeout=120)
        self.assertTrue(d["ok"], "scheduling readiness is never a blocker")
        return d, d["schedule"]

    def test_no_runner(self):
        d, s = self.schedule()
        self.assertEqual((s["platform_ok"], s["gh"]["logged_in"], s["gh"]["workflow_scope"]), (True, True, True))
        self.assertEqual(s["repo"], {"name": "someone/project", "private": True, "default_branch": "main"})
        self.assertEqual([p["problem"] for p in s["runners"]["problems"]], ["none"])
        self.assertTrue(any(w.startswith("schedule runner: none") for w in d["warnings"]))

    def test_a_service_in_its_own_session(self):
        self.runner(session_create=True)
        d, s = self.schedule()
        self.assertEqual([p["problem"] for p in s["runners"]["problems"]], ["session_create"])
        self.assertEqual(s["runners"]["local"][0]["path_has"], {"uv": True, "claude": True, "gh": False})

    def test_a_ready_runner(self):
        self.runner(session_create=False)
        d, s = self.schedule()
        self.assertEqual(s["runners"]["problems"], [])
        self.assertFalse(any(w.startswith("schedule") for w in d["warnings"]))

    def test_the_repository_as_github_spells_it(self):
        self.runner(session_create=False)
        git(self.project, "remote", "set-url", "origin", "https://github.com/Someone/Project.git")
        d, s = self.schedule()
        self.assertEqual(s["repo"]["name"], "someone/project")
        self.assertEqual(s["runners"]["problems"], [], "the same judgement schedule makes")

    def test_a_gh_that_cannot_run_or_answers_slowly_is_a_warning(self):
        import os

        bad = self.root / "bad-bin"
        bad.mkdir()
        (bad / "gh").write_text("not a program\n")
        os.chmod(bad / "gh", 0o755)
        d = self.cli_json("doctor", timeout=120, env={"PATH": f"{bad}{os.pathsep}{self.env['PATH']}"})
        self.assertTrue(d["ok"])
        self.assertTrue(any("gh" in w for w in d["warnings"]), d["warnings"])
        w = json.loads(self.world.read_text())
        w["slow"] = 30
        self.world.write_text(json.dumps(w))
        import time

        began = time.time()
        d = self.cli_json("doctor", timeout=120, env={"CLAUDE_SKILL_TEST_TIMINGS": json.dumps({"doctor_gh_wait": 2})})
        self.assertLess(time.time() - began, 25, "doctor does not wait out a slow gh")
        self.assertTrue(any("did not answer" in x for x in d["warnings"]), d["warnings"])

    def test_no_github_remote_and_no_gh_login(self):
        git(self.project, "remote", "remove", "origin")
        d, s = self.schedule()
        self.assertIn("error", s["repo"])
        self.assertTrue(any("GitHub remote" in x for x in d["warnings"]), d["warnings"])
        w = json.loads(self.world.read_text())
        w["auth"] = "none"
        self.world.write_text(json.dumps(w))
        d, s = self.schedule()
        self.assertFalse(s["gh"]["logged_in"])
        self.assertTrue(any("gh auth login" in x for x in d["warnings"]))
