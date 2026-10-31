"""A run from start to its recorded outcome, through the real CLI with the fake claude first on PATH: the handle, the argv and environment the worker gets, when stdin closes (J1), which result is the answer (J1b), each terminal state, and the refusals that cost nothing."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import shlex
import subprocess
import sys

from support.harness import ENTRY, FAST_TIMINGS, Sandbox, TERMINAL

PARENT_IDENTITY = {
    "CLAUDE_CODE_SESSION_ID": "parent-session-id",
    "CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/parent.sock",
    "CLAUDE_CODE_MESSAGING_TOKEN": "parent-token",
    "CLAUDE_CODE_BRIDGE_SESSION_ID": "bridge",
    "CLAUDE_PID": "4242",
    "CLAUDE_EFFORT": "max",
    "CLAUDE_CODE_SESSION_ATTENDED": "1",
}


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def worker_calls(calls):
    return [c for c in calls if "-p" in c["argv"]]


class Start(Sandbox):
    def test_reply_is_a_handle_with_the_wait_to_run_next(self):
        reply = self.start("hello [[fake:sleep:2]]")
        self.assertRegex(reply["run_id"], r"^\d{8}-\d{6}-run-[0-9a-f]{4}$")
        self.assertIn(reply["state"], ("running", "completed"))
        self.assertEqual(reply["next"]["command"], f'uv run "{ENTRY}" result --run {reply["run_id"]} --wait')
        self.assertTrue(reply["next"]["run_in_background"])
        self.assertEqual(reply["profile"], "write")
        self.assertEqual(reply["permission_mode"], "acceptEdits")
        self.assertFalse(reply["mode_mismatch"])
        self.assertEqual(reply["cwd"], str(self.project))
        self.assertEqual(reply["effort"], "high")
        self.wait_state(reply["run_id"])

    def test_the_worker_gets_the_profile_session_and_context(self):
        reply = self.start("hi", "--profile", "read-only", "--model", "haiku", "--effort", "low")
        self.wait_state(reply["run_id"])
        (call,) = worker_calls(self.fake_calls())
        argv = call["argv"]
        self.assertEqual(flag_value(argv, "--session-id"), reply["session_id"])
        self.assertEqual(flag_value(argv, "--permission-mode"), "dontAsk")
        self.assertEqual(flag_value(argv, "--model"), "haiku")
        self.assertEqual(flag_value(argv, "--effort"), "low")
        self.assertEqual(flag_value(argv, "--permission-prompts"), "none")
        self.assertIn("--include-hook-events", argv)
        sandbox = json.loads(flag_value(argv, "--settings"))["sandbox"]
        self.assertEqual(sandbox["filesystem"]["denyWrite"], [str(self.project)])
        i = argv.index("--disallowedTools") + 1
        tools = []
        while i < len(argv) and not argv[i].startswith("--"):
            tools.append(argv[i])
            i += 1
        self.assertEqual(tools, ["Skill(claude)", "Skill(claude:claude)", "Skill(headless-workers:claude)", "Monitor", "SendMessage", "PushNotification", "CronCreate", "RemoteTrigger", "Edit", "Write", "NotebookEdit"])
        self.assertIn("non-interactive", flag_value(argv, "--append-system-prompt"))
        self.assertEqual(call["cwd"], str(self.project))
        self.assertEqual([m["message"]["content"] for m in call["messages"]], ["hi"])
        self.assertTrue(call["messages"][0]["uuid"])

    def test_defaults_are_the_skills_not_the_users_settings(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"model": "opus", "effortLevel": "max", "permissions": {"defaultMode": "bypassPermissions"}}))
        reply = self.start("hi")
        self.wait_state(reply["run_id"])
        argv = worker_calls(self.fake_calls())[0]["argv"]
        self.assertEqual((flag_value(argv, "--model"), flag_value(argv, "--effort"), flag_value(argv, "--permission-mode")), ("sonnet", "high", "acceptEdits"))

    def test_worker_environment(self):
        reply = self.start("hi", env=PARENT_IDENTITY)
        self.wait_state(reply["run_id"])
        env = worker_calls(self.fake_calls())[0]["env"]
        for key in PARENT_IDENTITY:
            self.assertNotIn(key, env)
        self.assertEqual(env["CLAUDE_SKILL_RUN"], reply["run_id"])
        self.assertEqual(env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"], "1")
        self.assertEqual((env["BASH_DEFAULT_TIMEOUT_MS"], env["BASH_MAX_TIMEOUT_MS"]), ("600000", "3600000"))
        self.assertEqual(env["HOME"], str(self.home))

    def test_prompt_from_file_and_stdin(self):
        f = self.root / "p.txt"
        f.write_text("from a file")
        a = self.start("--prompt-file", str(f))
        b = self.cli_json("start", input="from stdin")
        for r in (a, b):
            self.wait_state(r["run_id"])
        texts = sorted(c["messages"][0]["message"]["content"] for c in worker_calls(self.fake_calls()))
        self.assertEqual(texts, ["from a file", "from stdin"])

    def test_empty_or_missing_prompt_is_an_argument_error(self):
        for args, kw in ((["start", "   "], {}), (["start"], {"input": ""}), (["start", "--prompt-file", "/nonexistent/p"], {})):
            reply = self.cli_json(*args, expect=2, **kw)
            self.assertEqual(reply["help"], "start --help")
        self.assertFalse(self.runs_dir().exists() and any(p for p in self.runs_dir().iterdir() if not p.name.startswith(".")))

    def test_cwd_flag_and_non_git_directory(self):
        other = self.root / "plain"
        other.mkdir()
        reply = self.start("hi", "--cwd", str(other))
        self.assertEqual(reply["cwd"], str(other))
        # The registry stays with the project the command ran in; the worker runs in --cwd.
        self.assertTrue((self.runs_dir() / reply["run_id"]).is_dir())
        bad = self.cli_json("start", "hi", "--cwd", str(self.root / "missing"), expect=2)
        self.assertIn("not a directory", bad["error"])
        reply2 = self.start("hi", cwd=other)
        self.assertTrue((other / ".claude-runs" / reply2["run_id"]).is_dir())
        self.assertEqual((other / ".claude-runs" / ".gitignore").read_text(), "*\n")


class Refusals(Sandbox):
    def test_inside_a_worker(self):
        reply = self.cli_json("start", "hi", expect=1, env={"CLAUDE_SKILL_RUN": "20261031-000000-run-0000"})
        self.assertIn("worker", reply["error"])
        self.assertEqual(self.fake_calls(), [])
        self.cli_json("status", env={"CLAUDE_SKILL_RUN": "x"})
        stop = self.cli_json("stop", "--run", "x", expect=1, env={"CLAUDE_SKILL_RUN": "x"})
        self.assertIn("worker", stop["error"])


class OldClaude(Sandbox):
    fake_version = "2.1.300"

    def test_below_the_floor_is_refused_before_any_run(self):
        reply = self.cli_json("start", "hi", expect=1)
        self.assertIn("2.1.314", reply["error"])
        self.assertIn("2.1.300", reply["error"])
        self.assertFalse(any(p for p in self.runs_dir().glob("2*")))
        self.assertEqual(worker_calls(self.fake_calls()), [])


class Outcomes(Sandbox):
    def result(self, run_id, *args):
        proc = self.cli("result", "--run", run_id, *args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        header, _, text = proc.stdout.partition("\n")
        return json.loads(header), text

    def test_completed_answer(self):
        reply = self.start("question [[fake:reply:the answer]]")
        header, text = self.result(reply["run_id"], "--wait")
        self.assertEqual(header["state"], "completed")
        self.assertEqual(header["exit_code"], 0)
        self.assertEqual(text, "the answer\n")
        self.assertEqual(header["message_bytes"], len("the answer"))
        self.assertEqual([a["head"] for a in header["answered"]], ["question [[fake:reply:the answer]]"])
        self.assertNotIn("next", header)

    def test_api_error_turn_is_failed(self):
        reply = self.start("x [[fake:error]]")
        header, _ = self.result(reply["run_id"], "--wait")
        self.assertEqual(header["state"], "failed")
        self.assertIn("api_error", header["error"])
        self.assertIn("500", header["error"])

    def test_auth_failure_is_reported_by_start(self):
        reply = self.cli_json("start", "x [[fake:auth_fail]]", expect=1)
        self.assertEqual(reply["state"], "failed")
        self.assertIn("Invalid API key", reply["error"])
        self.assertIn("Invalid API key", reply["stderr_tail"])
        self.assertNotIn("next", reply)

    def test_crash_mid_turn(self):
        reply = self.start("x [[fake:silent:1.5]] [[fake:crash]]")
        row = self.wait_state(reply["run_id"])
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["exit_code"], 1)
        self.assertIn("fake: crashed", row["stderr_tail"])

    def test_startup_failure_result(self):
        reply = self.cli_json("start", "x [[fake:startup_fail]]", expect=1)
        self.assertIn("worktree_resume_refused", reply["error"])

    def test_timeout(self):
        reply = self.start("x [[fake:sleep:30]]", "--timeout", "1")
        row = self.wait_state(reply["run_id"], timeout=20)
        self.assertEqual(row["state"], "timed_out")

    def test_followup_turn_does_not_become_the_answer(self):
        reply = self.start("x [[fake:reply:real answer]] [[fake:followup]]")
        header, text = self.result(reply["run_id"], "--wait")
        self.assertEqual(text, "real answer\n")
        self.assertEqual(header["followups"], 1)
        log = self.cli("log", "--run", reply["run_id"]).stdout
        self.assertIn("origin=task-notification", log)

    def test_hook_blocking_the_only_message_fails_the_run(self):
        reply = self.start("x [[fake:hook_block]]")
        header, _ = self.result(reply["run_id"], "--wait")
        self.assertEqual(header["state"], "failed")
        self.assertEqual(header["error"], "blocked_by_hook")
        self.assertEqual(header["blocked_by_hook"][0]["reason"], "blocked by fake hook")

    def test_turn_with_no_reply_and_no_notice(self):
        reply = self.start("x [[fake:silent0]]")
        header, _ = self.result(reply["run_id"], "--wait")
        self.assertEqual(header["possibly_blocked"], [header["answered"][0]["uuid"]])
        self.assertIn("possibly_blocked", [a["reason"] for a in header["attention"]])

    def test_mode_mismatch(self):
        reply = self.start("x [[fake:mode:default]] [[fake:sleep:1]]", "--profile", "auto")
        self.assertTrue(reply["mode_mismatch"])
        self.assertEqual(reply["permission_mode"], "default")

    def test_denials_and_edits_in_the_header(self):
        reply = self.start("x [[fake:write:out/a.txt]] [[fake:deny:/etc/x]] [[fake:edit_error:none.txt]]")
        header, _ = self.result(reply["run_id"], "--wait")
        self.assertEqual(header["files_edited"], [str(self.project / "out/a.txt")])
        self.assertEqual([d["tool"] for d in header["permission_denials"]], ["Write"])
        self.assertIn("/etc/x", header["permission_denials"][0]["input"])
        self.assertIn("shell command", header["files_edited_note"])

    def test_profile_exceptions_from_settings(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"sandbox": {"excludedCommands": ["docker"]}}))
        (self.project / ".claude").mkdir()
        (self.project / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"additionalDirectories": ["/data"]}}))
        reply = self.start("x", "--profile", "read-only")
        self.assertEqual(sorted(e["setting"] for e in reply["profile_exceptions"]), ["permissions.additionalDirectories", "sandbox.excludedCommands"])
        self.assertEqual(self.start("x", "--profile", "auto")["profile_exceptions"], [])

    def test_concurrent_writers(self):
        a = self.start("x [[fake:sleep:5]]")
        b = self.start("y [[fake:sleep:5]]")
        self.assertEqual(b["concurrent_writers"], [a["run_id"]])
        ro = self.start("z", "--profile", "read-only")
        self.assertEqual(ro["concurrent_writers"], [])
        self.cli_json("stop", "--run", a["run_id"], "--run", b["run_id"])


class StdinClose(Sandbox):
    """J1: stdin closes once every delivered message is answered, or — when no result names a message — after the idle grace with no hook running."""

    def test_closes_as_soon_as_the_message_is_answered(self):
        reply = self.start("x")
        self.wait_state(reply["run_id"])
        call = worker_calls(self.fake_calls())[0]
        self.assertIn("eof_at", call)
        self.assertEqual(call.get("exit"), 0)

    def test_without_uuids_closes_after_the_grace(self):
        reply = self.start("x [[fake:nouuid]] [[fake:reply:done]]")
        self.wait_state(reply["run_id"])
        header = json.loads(self.cli("result", "--run", reply["run_id"]).stdout.splitlines()[0])
        self.assertEqual(header["state"], "completed")
        self.assertTrue(header["answer_unconfirmed"])
        self.assertIsNone(header["answered"])

    def test_without_uuids_stdin_waits_out_the_grace(self):
        slow = json.dumps({**FAST_TIMINGS, "idle_grace": 2})
        reply = self.start("x [[fake:nouuid]]", env={"CLAUDE_SKILL_TEST_TIMINGS": slow})
        self.wait_state(reply["run_id"], timeout=20)
        call = worker_calls(self.fake_calls())[0]
        self.assertGreaterEqual(call["eof_at"] - call["results_at"][-1], 1.8, "stdin closed before stdout had been quiet for the grace")

    def test_an_open_hook_keeps_stdin_open(self):
        reply = self.start("x [[fake:nouuid]] [[fake:late_hook:2]]")
        self.wait_state(reply["run_id"], timeout=20)
        call = worker_calls(self.fake_calls())[0]
        self.assertGreaterEqual(call["eof_at"], call["late_hook_done"], "stdin closed while a hook was still running")

    def test_answered_message_closes_even_with_a_hook_running(self):
        reply = self.start("x [[fake:late_hook:2]]")
        self.wait_state(reply["run_id"], timeout=20)
        call = worker_calls(self.fake_calls())[0]
        self.assertLess(call["eof_at"], call["late_hook_done"])


class Finishing(Sandbox):
    def test_process_alive_after_stdin_closed(self):
        reply = self.start("x [[fake:reply:answer]] [[fake:linger:6]]")
        row = self.wait_state(reply["run_id"], states=("finishing",))
        self.assertEqual(row["state"], "finishing")
        proc = self.cli("result", "--run", reply["run_id"], "--wait")
        header, _, text = proc.stdout.partition("\n")
        header = json.loads(header)
        self.assertEqual(header["state"], "finishing")
        self.assertEqual([a["reason"] for a in header["attention"]], ["finishing"])
        self.assertEqual(text, "answer\n")
        self.assertIn("--wait", header["next"]["command"])
        self.assertEqual(self.wait_state(reply["run_id"], timeout=20)["state"], "completed")

    def test_follow_up_turns_after_close_still_end_the_wait_with_the_answer(self):
        reply = self.start("x [[fake:reply:the real answer]] [[fake:followups_after_close:6]]")
        proc = self.cli("result", "--run", reply["run_id"], "--wait", "--wait-timeout", "15")
        header, _, text = proc.stdout.partition("\n")
        header = json.loads(header)
        self.assertEqual(header["state"], "finishing")
        self.assertEqual([a["reason"] for a in header["attention"]], ["finishing"])
        self.assertEqual(text, "the real answer\n", "a finishing run's answer is decided; follow-ups are not it")
        self.assertIn("answer", header["note"])
        self.cli_json("stop", "--run", reply["run_id"])

    def test_finishing_schema_run_has_its_json(self):
        schema = self.root / "s.json"
        schema.write_text("{}")
        reply = self.start('x [[fake:schema:{"v": 1}]] [[fake:linger:6]]', "--schema", str(schema))
        self.wait_state(reply["run_id"], states=("finishing",))
        doc = json.loads(self.cli("result", "--run", reply["run_id"]).stdout)
        self.assertEqual(doc["json"], {"v": 1})

    def test_silent_finishing_run_shows_stalled(self):
        reply = self.start("x [[fake:linger:8]]", env={"CLAUDE_SKILL_TEST_TIMINGS": json.dumps({**FAST_TIMINGS, "finishing_attention": 100})})
        self.wait_state(reply["run_id"], states=("finishing",))
        self.wait_for(lambda: self.status(reply["run_id"])["state"] == "stalled", timeout=10, what="stalled")
        self.cli_json("stop", "--run", reply["run_id"])


class NextCommand(Sandbox):
    def run_next(self, command, cwd):
        argv = shlex.split(command)
        self.assertEqual(argv[:2], ["uv", "run"])
        return subprocess.run([sys.executable, *argv[2:]], cwd=cwd, capture_output=True, text=True, env=self.env, timeout=60)

    def test_next_reaches_the_registry_it_was_given(self):
        elsewhere = self.root / "elsewhere dir"
        elsewhere.mkdir()
        for flags in (["--project", str(self.project)], ["--runs-dir", str(self.root / "my reg")]):
            with self.subTest(flags):
                reply = self.cli_json("start", "hi", *flags, cwd=elsewhere)
                proc = self.run_next(reply["next"]["command"], elsewhere)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(json.loads(proc.stdout.splitlines()[0])["run_id"], reply["run_id"])

    def test_plain_next_has_no_registry_flag(self):
        reply = self.start("hi")
        self.assertNotIn("--runs-dir", reply["next"]["command"])
