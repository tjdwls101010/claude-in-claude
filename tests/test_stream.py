"""Reading a worker's stdout: the summary a row is built from, the log lines, and which result is the run's answer (J1b).

Inputs are real stream-json captures (tests/support/fixtures); the expected values were read off those files by hand, with the message positions (`after_line`) taken from where each message's `command_lifecycle queued` line or turn sits in the capture.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support.harness import FIXTURES, engine

cli = engine("claude.claude_cli")


def load(name, upto=None, start=0):
    lines = [json.loads(l) for l in (FIXTURES / name).read_text().splitlines() if l.strip()]
    return lines[start:upto]


def msg(uuid, after_line, text="m", kind="send", priority="next"):
    return {"uuid": uuid, "after_line": after_line, "head": text[:80], "kind": kind, "priority": priority}


HB = {"u1": "8d115359-8bb0-4140-83e5-783bb78a5f28", "u2": "e8ea0958-f86b-4f3c-81d7-8064a0be4bb0", "u3": "4005e490-7171-4c27-882a-235650f57c67"}
HS = {"u1": "34ae8b78-8004-4394-b79f-a46ce1fe3d1d", "u2": "0581868c-ca0c-452b-a797-53b284c8afa1", "u3": "7fb72344-3b7d-415b-9bc8-05c8b8d343dc"}
NM = {"u1": "e6aa4655-28f7-4c9f-837c-884cda8edac8", "u2": "2c350dca", "u3": "18b18546"}


def full_uuid(prefix, name="send_next_merged.jsonl"):
    for e in load(name):
        u = e.get("command_uuid") or ""
        if u.startswith(prefix):
            return u
    raise KeyError(prefix)


class Summary(unittest.TestCase):
    def test_basic_run(self):
        s = cli.summarize(load("basic_write.jsonl"))
        self.assertEqual(s["init"], {"permission_mode": "auto", "model": "claude-haiku-5-5", "cwd": "/work/exp1", "claude_code_version": "2.1.314", "session_id": "57132294-1a16-44b3-8555-21c086e066db"})
        self.assertEqual(s["files_edited"], ["/work/exp1/out.txt"])
        self.assertEqual(s["tool_calls"], {"Read": 1, "Write": 1})
        self.assertEqual(s["last_message"], "The content of `note.txt` is **hello**.\n\nI created `out.txt` in the same directory with the content `x`.")
        self.assertEqual(len(s["results"]), 1)
        self.assertAlmostEqual(s["cost_usd"], 0.00380097, places=8)
        self.assertEqual(s["open_hooks"], 0)
        self.assertEqual(s["in_progress"], [])
        self.assertEqual(s["rate_limit"]["status"], "allowed")
        self.assertEqual(s["rate_limit"]["five_hour"], 0.02)
        self.assertEqual(s["rate_limit"]["seven_day"], 0.42)

    def test_denials_and_edits(self):
        first_turn = load("denials.jsonl", upto=22)
        s = cli.summarize(first_turn)
        self.assertEqual(s["files_edited"], ["/work/exp9/proj/a.txt"])
        self.assertEqual([d["tool"] for d in s["denials"]], ["Write", "SandboxNetworkAccess"])
        self.assertIn("/work/exp9/outside/c.txt", s["denials"][0]["input"])
        both = cli.summarize(load("denials.jsonl"))
        self.assertEqual(both["files_edited"], ["/work/exp9/proj/a.txt", "/work/exp9/outside/c.txt"])
        self.assertEqual(len(both["results"]), 2)

    def test_tool_in_progress(self):
        s = cli.summarize(load("sigint.jsonl", upto=3))
        self.assertEqual([(p["tool"], p["summary"]) for p in s["in_progress"]], [("Bash", "python3 -c 'import time; time.sleep(25); print(42)'")])
        self.assertEqual(cli.summarize(load("sigint.jsonl", upto=6))["in_progress"], [])

    def test_open_hooks(self):
        self.assertEqual(cli.summarize(load("hook_stop.jsonl", upto=35))["open_hooks"], 1)
        self.assertEqual(cli.summarize(load("hook_stop.jsonl"))["open_hooks"], 0)

    def test_subagent_tools_are_not_main_thread_calls(self):
        s = cli.summarize(load("subagent.jsonl"))
        self.assertEqual(s["tool_calls"], {"Bash": 3, "Agent": 1})

    def test_retry_is_the_last_event(self):
        events = load("basic_write.jsonl", upto=6) + [{"type": "system", "subtype": "api_retry", "attempt": 2, "max_retries": 10, "retry_delay_ms": 4000, "error_status": 529, "error": "overloaded", "uuid": "x", "session_id": "s"}]
        s = cli.summarize(events)
        self.assertTrue(s["last_event_is_retry"])
        self.assertEqual(s["retry"]["attempt"], 2)
        self.assertFalse(cli.summarize(load("basic_write.jsonl"))["last_event_is_retry"])

    def test_cost_is_cumulative_and_usage_sums_turns(self):
        s = cli.summarize(load("send_next_merged.jsonl"))
        self.assertAlmostEqual(s["cost_usd"], 0.00396037, places=8)
        r = [e for e in load("send_next_merged.jsonl") if e.get("type") == "result"]
        self.assertEqual(s["usage"]["output_tokens"], sum(x["usage"]["output_tokens"] for x in r))

    def test_unparsed_lines_are_counted(self):
        d = Path(tempfile.mkdtemp())
        path = d / "events.jsonl"
        path.write_text((FIXTURES / "basic_write.jsonl").read_text() + "not json\n{\"type\": \n")
        events, unparsed = cli.read_events(path)
        self.assertEqual(len(events), 15)
        self.assertEqual(unparsed, 2)
        self.assertEqual(cli.read_events(d / "missing.jsonl"), ([], 0))


class Log(unittest.TestCase):
    def test_basic_run(self):
        self.assertEqual(
            cli.log_lines(load("basic_write.jsonl"), rel_to="/work/exp1"),
            [
                "init model=claude-haiku-5-5 mode=auto cwd=/work/exp1",
                "read note.txt",
                "ratelimit allowed 5h=2% 7d=42%",
                "write out.txt",
                "msg The content of `note.txt` is **hello**.",
                "",
                "    I created `out.txt` in the same directory with the content `x`.",
                "result success turns=3 terminal=completed cost=$0.0038",
            ],
        )

    def test_failed_bash_shows_exit_code_and_output(self):
        lines = cli.log_lines(load("bash_timeout.jsonl"), rel_to="/work/exp_a")
        i = lines.index("""bash exit=143 out=26B python3 -c "import time; time.sleep(12); print('A-DONE')\"""")
        self.assertEqual(lines[i + 1], "    Command timed out after 8s")
        self.assertIn("""bash exit=143 out=27B python3 -c "import time; time.sleep(25); print('B-DONE')\"""", lines)
        self.assertFalse(any(l.startswith(("hook", "system")) for l in lines))

    def test_denied_calls_and_sandbox_violation(self):
        lines = cli.log_lines(load("denials.jsonl", upto=22), rel_to="/work/exp9/proj")
        self.assertIn("write a.txt", lines)
        self.assertIn("bash exit=0 out=0B echo b > b.txt", lines)
        denied = [l for l in lines if l.startswith("denied ")]
        self.assertEqual(len(denied), 2)
        self.assertTrue(denied[0].startswith('denied Write {"file_path": "/work/exp9/outside/c.txt"'))
        self.assertTrue(denied[1].startswith("denied SandboxNetworkAccess"))
        self.assertFalse(any(l.startswith("write ") and "outside" in l for l in lines))
        curl = [l for l in lines if l.startswith("bash exit=56")]
        self.assertEqual(len(curl), 1)

    def test_sent_messages_and_followup_results(self):
        u2 = full_uuid("2c350dca")
        lines = cli.log_lines(load("send_next_merged.jsonl"), rel_to="/work/exp12", messages=[msg(NM["u1"], 0, kind="prompt"), msg(u2, 9, "also say BLUE")])
        self.assertIn("sent next also say BLUE", lines)
        self.assertLess(lines.index("sent next also say BLUE"), lines.index("bash exit=0 out=1B python3 -c 'import time; time.sleep(12); print(\"A\")'"))
        follow = cli.log_lines(load("background_followup.jsonl"), rel_to="/work/exp3")
        self.assertEqual(follow[-1], "result success turns=1 terminal=completed cost=$0.0014 origin=task-notification")

    def test_subagent_line(self):
        lines = cli.log_lines(load("subagent.jsonl"), rel_to="/work/exp13")
        agent = [l for l in lines if l.startswith("agent ")]
        self.assertEqual(len(agent), 1)
        self.assertTrue(agent[0].startswith("agent web-fetch Fetch github.com homepage tools=1 out="), agent[0])

    def test_running_call_at_the_end(self):
        lines = cli.log_lines(load("sigint.jsonl", upto=3), rel_to="/work/exp4")
        self.assertEqual(lines[-1], "running Bash python3 -c 'import time; time.sleep(25); print(42)'")


class FinalResult(unittest.TestCase):
    def test_merged_messages_answer_with_the_last_turn(self):
        u2, u3 = full_uuid("2c350dca"), full_uuid("18b18546")
        f = cli.final_result(load("send_next_merged.jsonl"), [msg(NM["u1"], 0, "first", kind="prompt"), msg(u2, 9, "blue"), msg(u3, 19, "green")])
        self.assertEqual(f["result"]["text"], "GREEN")
        self.assertEqual(f["answered"], [{"uuid": u3, "head": "green"}])
        self.assertEqual(f["unanswered"], [])
        self.assertFalse(f["last_message_unanswered"])
        self.assertIsNone(f["error"])
        self.assertEqual(cli.answered_uuids(load("send_next_merged.jsonl")), {NM["u1"], u2, u3})

    def test_last_message_without_any_result_after_it(self):
        u2, u3 = full_uuid("2c350dca"), full_uuid("18b18546")
        f = cli.final_result(load("send_next_merged.jsonl", upto=21), [msg(NM["u1"], 0, "first", kind="prompt"), msg(u2, 9, "blue"), msg(u3, 19, "green")])
        self.assertEqual(f["result"]["text"], "The command printed `A`.\n\nBLUE")
        self.assertEqual(sorted(a["uuid"] for a in f["answered"]), sorted([NM["u1"], u2]))
        self.assertTrue(f["last_message_unanswered"])
        self.assertEqual(f["unanswered"], [{"uuid": u3, "head": "green"}])

    def test_followup_result_does_not_replace_the_answer(self):
        f = cli.final_result(load("background_followup.jsonl"), [msg(None, 0, kind="prompt"), msg(None, 17), msg(None, 27)])
        self.assertTrue(f["result"]["text"].startswith("The foreground run was blocked, so I started"))
        self.assertIsNone(f["answered"])
        self.assertTrue(f["answer_unconfirmed"])
        self.assertEqual(f["followups"], 1)

    def test_blocked_messages_keep_the_earlier_answer(self):
        for name, ids, reason in (("hook_block.jsonl", HB, "blocked by test hook"), ("hook_stop.jsonl", HS, "stopped by test hook")):
            with self.subTest(name):
                positions = (0, 15, 31) if name == "hook_block.jsonl" else (0, 15, 37)
                messages = [msg(ids["u1"], positions[0], "first", kind="prompt"), msg(ids["u2"], positions[1], "mid"), msg(ids["u3"], positions[2], "next turn")]
                f = cli.final_result(load(name), messages)
                self.assertTrue(f["result"]["text"].startswith("The command ran in the foreground"))
                self.assertEqual(f["answered"], [{"uuid": ids["u1"], "head": "first"}])
                self.assertTrue(f["last_message_blocked"])
                self.assertEqual([(b["uuid"], b["reason"]) for b in f["blocked_by_hook"]], [(ids["u2"], reason), (ids["u3"], reason)])
                self.assertEqual(f["unanswered"], [])
                self.assertIsNone(f["error"])

    def test_blocked_in_turn_message_as_the_last_one(self):
        f = cli.final_result(load("hook_block.jsonl", upto=31), [msg(HB["u1"], 0, "first", kind="prompt"), msg(HB["u2"], 15, "mid")])
        self.assertTrue(f["last_message_blocked"])
        self.assertEqual(f["answered"], [{"uuid": HB["u1"], "head": "first"}])

    def test_only_message_blocked_is_a_failure(self):
        f = cli.final_result(load("hook_block.jsonl", start=31), [msg(HB["u3"], 0, "only", kind="prompt")])
        self.assertIsNone(f["result"])
        self.assertEqual(f["error"], "blocked_by_hook")
        self.assertTrue(f["last_message_blocked"])

    def test_turn_ended_with_no_reply_and_no_hook_notice(self):
        init = load("basic_write.jsonl")[4]
        silent = [init, {"type": "result", "subtype": "success", "is_error": False, "num_turns": 0, "result": "", "user_message_uuids": ["aaaa"], "total_cost_usd": 0, "session_id": "s", "uuid": "r"}]
        f = cli.final_result(silent, [msg("aaaa", 0, kind="prompt")])
        self.assertEqual(f["possibly_blocked"], ["aaaa"])
        local = [init, {**silent[1], "local_command": "compact"}]
        self.assertEqual(cli.final_result(local, [msg("aaaa", 0, kind="prompt")])["possibly_blocked"], [])

    def test_error_before_init_is_a_startup_failure(self):
        events = [{"type": "result", "subtype": "error_during_execution", "is_error": True, "num_turns": 0, "errors": ["Error: cannot resume into worktree /r/.claude/worktrees/g-1: gone"], "startup_failure_reason": "worktree_resume_refused", "session_id": "s", "uuid": "r"}]
        f = cli.final_result(events, [msg("aaaa", 0, kind="prompt")])
        self.assertIsNone(f["result"])
        self.assertIn("worktree_resume_refused", f["error"])
        self.assertIn("cannot resume into worktree", f["error"])

    def test_interrupted_turn_is_the_answer_with_its_error(self):
        f = cli.final_result(load("sigint.jsonl", upto=6), [msg(None, 0, kind="prompt")])
        self.assertTrue(f["result"]["is_error"])
        self.assertEqual(f["result"]["terminal_reason"], "aborted_tools")

    def test_structured_output(self):
        f = cli.final_result(load("schema.jsonl"), [msg(None, 0, kind="prompt"), msg(None, 6)])
        self.assertEqual(f["result"]["structured_output"], {"word": "banana", "n": 2})


class Encode(unittest.TestCase):
    def test_user_message_line(self):
        line = cli.encode_user_message("hello", "abcd", "now")
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(json.loads(line), {"type": "user", "message": {"role": "user", "content": "hello"}, "parent_tool_use_id": None, "uuid": "abcd", "priority": "now"})
        self.assertNotIn("priority", json.loads(cli.encode_user_message("x", "u", None)))


if __name__ == "__main__":
    unittest.main()
