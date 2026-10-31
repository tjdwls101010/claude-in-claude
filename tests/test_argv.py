"""What the worker is started with: argv per profile, the worker's environment, and the settings that widen a profile.

Expected flag strings are written out from the plan's measured bundles (exp6·exp9: the read-only and write sandboxes; exp12·exp17: the disallowed list), not derived from the code under test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support.harness import engine

cli = engine("claude.claude_cli")

DISALLOWED = ["Skill(claude)", "Skill(claude:claude)", "Skill(headless-workers:claude)", "Monitor", "SendMessage", "PushNotification", "CronCreate", "RemoteTrigger"]
COMMON_HEAD = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-hook-events", "--permission-prompts", "none"]


def flag_value(argv, flag):
    i = argv.index(flag)
    return argv[i + 1]


def flag_values(argv, flag):
    """The values after a variadic flag, up to the next flag."""
    i = argv.index(flag) + 1
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


class ProfileArgv(unittest.TestCase):
    def build(self, profile, **kw):
        settings = {"profile": profile, "model": "sonnet", "effort": "high"}
        return cli.build_argv(settings, session_id="11111111-2222-3333-4444-555555555555", resume=kw.pop("resume", False), cwd="/work/proj", **kw)

    def test_read_only(self):
        argv = self.build("read-only")
        self.assertEqual(argv[: len(COMMON_HEAD)], COMMON_HEAD)
        self.assertEqual(flag_value(argv, "--permission-mode"), "dontAsk")
        self.assertEqual(flag_values(argv, "--allowedTools"), ["Bash"])
        self.assertEqual(flag_values(argv, "--disallowedTools"), DISALLOWED + ["Edit", "Write", "NotebookEdit"])
        self.assertEqual(
            json.loads(flag_value(argv, "--settings")),
            {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True, "filesystem": {"denyWrite": ["/work/proj"], "allowWrite": ["~/.cache"]}}},
        )

    def test_write(self):
        argv = self.build("write")
        self.assertEqual(flag_value(argv, "--permission-mode"), "acceptEdits")
        self.assertEqual(flag_values(argv, "--allowedTools"), ["Bash"])
        self.assertEqual(flag_values(argv, "--disallowedTools"), DISALLOWED)
        self.assertEqual(
            json.loads(flag_value(argv, "--settings")),
            {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True, "filesystem": {"allowWrite": ["~/.cache"]}}},
        )

    def test_auto_has_no_sandbox(self):
        argv = self.build("auto")
        self.assertEqual(flag_value(argv, "--permission-mode"), "auto")
        self.assertEqual(flag_values(argv, "--disallowedTools"), DISALLOWED)
        self.assertNotIn("--settings", argv)
        self.assertNotIn("--allowedTools", argv, "auto leaves every call to the classifier")

    def test_one_disallowed_flag(self):
        for profile in ("read-only", "write", "auto"):
            self.assertEqual(self.build(profile).count("--disallowedTools"), 1, profile)

    def test_model_effort_and_session(self):
        argv = self.build("write")
        self.assertEqual(flag_value(argv, "--model"), "sonnet")
        self.assertEqual(flag_value(argv, "--effort"), "high")
        self.assertEqual(flag_value(argv, "--session-id"), "11111111-2222-3333-4444-555555555555")
        self.assertNotIn("--resume", argv)
        resumed = self.build("write", resume=True)
        self.assertEqual(flag_value(resumed, "--resume"), "11111111-2222-3333-4444-555555555555")
        self.assertNotIn("--session-id", resumed)

    def test_worker_context_is_appended_every_turn(self):
        for resume in (False, True):
            text = flag_value(self.build("write", resume=resume), "--append-system-prompt")
            self.assertEqual(text, cli.worker_context())
        ctx = cli.worker_context().lower()
        for needle in ("non-interactive", "final message", "commit", "push"):
            self.assertIn(needle, ctx)

    def test_schema_text_is_passed_inline(self):
        schema = '{"type": "object", "properties": {"ok": {"type": "boolean"}}}'
        argv = self.build("read-only", schema_text=schema)
        self.assertEqual(flag_value(argv, "--json-schema"), schema)
        self.assertNotIn("--json-schema", self.build("read-only"))

    def test_worktree_member_merges_base_ref_into_the_same_settings(self):
        argv = self.build("write", worktree="g-1")
        self.assertEqual(flag_value(argv, "--worktree"), "g-1")
        self.assertEqual(argv.count("--settings"), 1)
        settings = json.loads(flag_value(argv, "--settings"))
        self.assertEqual(settings["worktree"], {"baseRef": "head"})
        self.assertTrue(settings["sandbox"]["enabled"])
        auto = json.loads(flag_value(self.build("auto", worktree="g-2"), "--settings"))
        self.assertEqual(auto, {"worktree": {"baseRef": "head"}})

    def test_every_flag_after_a_variadic_list_is_a_flag(self):
        """Commander's variadic --allowedTools and --disallowedTools swallow plain words, so whatever follows each starts with `--`."""
        argv = self.build("read-only", schema_text="{}", worktree="g-1")
        for flag in ("--allowedTools", "--disallowedTools"):
            i = argv.index(flag) + 1 + len(flag_values(argv, flag))
            self.assertLess(i, len(argv), f"{flag} is last")
            self.assertTrue(argv[i].startswith("--"), argv[i])

    def test_unknown_profile_is_refused(self):
        with self.assertRaises(ValueError):
            self.build("bypass")


class WorkerEnv(unittest.TestCase):
    PARENT = {
        "PATH": "/bin",
        "HOME": "/Users/me",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDE_CODE_PLUGIN_DIRS": "/plugins",
        "CLAUDE_CODE_SESSION_ID": "parent-session",
        "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/s.sock",
        "CLAUDE_CODE_MESSAGING_TOKEN": "tok",
        "CLAUDE_CODE_BRIDGE_SESSION_ID": "bridge",
        "CLAUDE_PID": "123",
        "CLAUDE_EFFORT": "max",
        "CLAUDE_CODE_SESSION_ATTENDED": "1",
    }

    def test_parent_identity_is_removed_and_the_rest_kept(self):
        env = cli.worker_env(self.PARENT, "20261031-000000-run-abcd")
        for gone in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ATTENDED"):
            self.assertNotIn(gone, env)
        for kept in ("PATH", "HOME", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_PLUGIN_DIRS"):
            self.assertEqual(env[kept], self.PARENT[kept])

    def test_skill_variables_are_added(self):
        env = cli.worker_env(self.PARENT, "20261031-000000-run-abcd")
        self.assertEqual(env["CLAUDE_SKILL_RUN"], "20261031-000000-run-abcd")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")
        self.assertEqual(env["BASH_DEFAULT_TIMEOUT_MS"], "600000")
        self.assertEqual(env["BASH_MAX_TIMEOUT_MS"], "3600000")

    def test_larger_shell_timeouts_are_kept(self):
        env = cli.worker_env({**self.PARENT, "BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "100"}, "r")
        self.assertEqual(env["BASH_DEFAULT_TIMEOUT_MS"], "900000")
        self.assertEqual(env["BASH_MAX_TIMEOUT_MS"], "3600000")

    def test_parent_env_is_not_mutated(self):
        parent = dict(self.PARENT)
        cli.worker_env(parent, "r")
        self.assertEqual(parent, self.PARENT)


class ProfileExceptions(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.home = self.root / "home"
        self.proj = self.root / "proj"
        (self.home / ".claude").mkdir(parents=True)
        (self.proj / ".claude").mkdir(parents=True)

    def write(self, path, obj):
        path.write_text(json.dumps(obj))

    def found(self, profile, **kw):
        return cli.profile_exceptions(str(self.proj), profile, env={"HOME": str(self.home)}, managed_dir=str(self.root / "managed"), **kw)

    def settings_named(self, items):
        return sorted(x["setting"] for x in items)

    def test_nothing_set_means_no_exception(self):
        self.assertEqual(self.found("read-only"), [])

    def test_sandbox_widening_from_user_and_project(self):
        self.write(self.home / ".claude" / "settings.json", {"sandbox": {"excludedCommands": ["docker"], "network": {"allowedDomains": ["pypi.org"]}}, "permissions": {"allow": ["WebFetch(domain:github.com)", "Bash(ls:*)"]}})
        self.write(self.proj / ".claude" / "settings.local.json", {"sandbox": {"filesystem": {"allowWrite": ["/var/tmp/x"]}}, "permissions": {"additionalDirectories": ["/data"]}})
        got = self.found("read-only")
        self.assertEqual(self.settings_named(got), ["permissions.additionalDirectories", "permissions.allow WebFetch(domain:…)", "sandbox.excludedCommands", "sandbox.filesystem.allowWrite", "sandbox.network.allowedDomains"])
        by = {x["setting"]: x for x in got}
        self.assertEqual(by["sandbox.excludedCommands"]["value"], ["docker"])
        self.assertEqual(by["sandbox.excludedCommands"]["file"], str(self.home / ".claude" / "settings.json"))
        self.assertEqual(by["permissions.allow WebFetch(domain:…)"]["value"], ["github.com"])
        self.assertTrue(all(x["effect"] for x in got))

    def test_auto_reports_only_what_still_applies(self):
        self.write(self.home / ".claude" / "settings.json", {"sandbox": {"excludedCommands": ["docker"]}, "env": {"BASH_DEFAULT_TIMEOUT_MS": "1000"}})
        self.assertEqual(self.settings_named(self.found("auto")), ["env.BASH_DEFAULT_TIMEOUT_MS"])
        self.assertEqual(self.settings_named(self.found("write")), ["env.BASH_DEFAULT_TIMEOUT_MS", "sandbox.excludedCommands"])

    def test_settings_env_that_overrides_the_worker_env(self):
        self.write(self.proj / ".claude" / "settings.json", {"env": {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "0", "BASH_MAX_TIMEOUT_MS": "5000", "OTHER": "x"}})
        self.assertEqual(self.settings_named(self.found("write")), ["env.BASH_MAX_TIMEOUT_MS", "env.CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"])

    def test_managed_sandbox_disabled(self):
        (self.root / "managed").mkdir()
        self.write(self.root / "managed" / "managed-settings.json", {"sandbox": {"enabled": False}})
        got = self.found("read-only")
        self.assertEqual(self.settings_named(got), ["sandbox.enabled"])
        (self.root / "managed" / "managed-settings.d").mkdir()
        self.write(self.root / "managed" / "managed-settings.d" / "10-net.json", {"sandbox": {"network": {"allowedDomains": ["corp.example"]}}})
        self.assertIn("sandbox.network.allowedDomains", self.settings_named(self.found("write")))

    def test_edit_allow_rules_outside_the_directory(self):
        self.write(self.home / ".claude" / "settings.json", {"permissions": {"allow": ["Edit(/etc/**)", "Write(//tmp/out/**)", "Edit(src/**)", "Edit(./docs/**)", "Read(/x)"]}})
        got = self.found("write")
        self.assertEqual(self.settings_named(got), ["permissions.allow Edit/Write outside"])
        self.assertEqual(got[0]["value"], ["Edit(/etc/**)", "Write(//tmp/out/**)"])

    def test_unreadable_settings_are_reported_not_fatal(self):
        (self.home / ".claude" / "settings.json").write_text("{not json")
        got = self.found("write")
        self.assertEqual(self.settings_named(got), ["unreadable settings file"])

    def test_project_files_at_the_git_top_level_count(self):
        sub = self.proj / "pkg"
        sub.mkdir()
        self.write(self.proj / ".claude" / "settings.json", {"sandbox": {"excludedCommands": ["make"]}})
        got = cli.profile_exceptions(str(sub), "write", env={"HOME": str(self.home)}, managed_dir=str(self.root / "managed"), project_roots=[str(self.proj)])
        self.assertEqual(self.settings_named(got), ["sandbox.excludedCommands"])


class TurnPreamble(unittest.TestCase):
    def test_nothing_to_say_for_a_lone_run(self):
        for profile in ("read-only", "write", "auto"):
            self.assertIsNone(cli.turn_preamble(profile))

    def test_group_and_worktree_facts(self):
        text = cli.turn_preamble("write", group={"name": "g", "index": 2, "size": 3}, worktree={"path": "/r/.claude/worktrees/g-2", "base": "abc123", "uncommitted": 4})
        self.assertIn("member 2 of 3 in group g", text)
        self.assertIn("/r/.claude/worktrees/g-2", text)
        self.assertIn("abc123", text)
        self.assertIn("4 uncommitted", text)


class WorktreeLocation(unittest.TestCase):
    def test_claude_code_naming(self):
        self.assertEqual(cli.worktree_location("/r", "grp-1"), {"path": "/r/.claude/worktrees/grp-1", "branch": "worktree-grp-1"})


if __name__ == "__main__":
    unittest.main()
