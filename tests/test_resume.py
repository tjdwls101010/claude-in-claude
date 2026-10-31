"""Continuing a session: every setting re-sent to the resumed process, a flag changing it from that turn on, sessions the registry never saw, and the refusals around a live session."""

from __future__ import annotations

import json
import uuid

from support.harness import Sandbox


def worker_calls(calls):
    return [c for c in calls if "-p" in c["argv"]]


def strip_session(argv):
    """argv without the session flag pair, which is the one thing that differs between a start and its resume."""
    out = list(argv)
    for flag in ("--session-id", "--resume"):
        if flag in out:
            i = out.index(flag)
            del out[i : i + 2]
    return out


class Resume(Sandbox):
    def test_every_setting_is_sent_again(self):
        schema = self.root / "s.json"
        schema.write_text('{"type": "object", "properties": {"ok": {"type": "boolean"}}}')
        first = self.start("x [[fake:schema]]", "--profile", "read-only", "--model", "haiku", "--effort", "low", "--schema", str(schema))
        self.wait_state(first["run_id"])
        again = self.cli_json("resume", first["run_id"], "and then [[fake:schema]]")
        self.assertEqual(again["session_id"], first["session_id"])
        self.assertNotEqual(again["run_id"], first["run_id"])
        self.assertEqual(again["permission_mode"], "dontAsk")
        self.wait_state(again["run_id"])
        a, b = worker_calls(self.fake_calls())
        self.assertEqual(b["argv"][b["argv"].index("--resume") + 1], first["session_id"])
        self.assertEqual(strip_session(a["argv"]), strip_session(b["argv"]))
        self.assertEqual(a["cwd"], b["cwd"])
        self.assertEqual(b["env"]["CLAUDE_SKILL_RUN"], again["run_id"])
        doc = json.loads(self.cli("result", "--run", again["run_id"]).stdout)
        self.assertEqual(doc["json"], {"ok": True})

    def test_a_flag_changes_the_profile_from_that_turn_on(self):
        first = self.start("x", "--profile", "read-only")
        self.wait_state(first["run_id"])
        second = self.cli_json("resume", first["session_id"], "y", "--profile", "auto")
        self.assertEqual(second["profile_changed_from"], "read-only")
        self.assertEqual(second["permission_mode"], "auto")
        self.wait_state(second["run_id"])
        third = self.cli_json("resume", second["run_id"], "z")
        self.assertEqual(third["profile"], "auto")
        self.assertNotIn("profile_changed_from", third)
        self.wait_state(third["run_id"])

    def test_session_the_registry_never_saw(self):
        sid = str(uuid.uuid4())
        (self.state / "sessions").mkdir(exist_ok=True)
        (self.state / "sessions" / f"{sid}.json").write_text(json.dumps({"turns": 1, "cwd": str(self.project), "worktree": None}))
        need = self.cli_json("resume", sid, "hi", expect=2)
        self.assertIn("--profile", need["error"])
        reply = self.cli_json("resume", sid, "hi", "--profile", "read-only")
        self.assertEqual(reply["session_id"], sid)
        self.assertIn("not in the registry", reply["note"])
        self.assertEqual(self.wait_state(reply["run_id"])["state"], "completed")

    def test_session_claude_does_not_know_fails_at_start(self):
        reply = self.cli_json("resume", str(uuid.uuid4()), "hi", "--profile", "write", expect=1)
        self.assertEqual(reply["state"], "failed")
        self.assertIn("No conversation found", reply["error"])

    def test_unknown_ref_that_is_not_a_session(self):
        self.assertIn("no run or session", self.cli_json("resume", "nope", "hi", expect=1)["error"])

    def test_prompt_is_required(self):
        first = self.start("x")
        self.wait_state(first["run_id"])
        self.assertEqual(self.cli_json("resume", first["run_id"], input="", expect=2)["help"], "resume --help")
        self.cli_json("resume", expect=2)

    def test_stopped_run_can_be_resumed(self):
        first = self.start("x [[fake:sleep:30]]")
        self.cli_json("stop", "--run", first["run_id"])
        again = self.cli_json("resume", first["run_id"], "carry on [[fake:reply:resumed]]")
        self.assertEqual(self.wait_state(again["run_id"])["state"], "completed")
        self.assertEqual(self.cli("result", "--run", again["run_id"]).stdout.split("\n", 1)[1], "resumed\n")
