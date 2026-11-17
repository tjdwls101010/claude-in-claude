"""The workflow file a schedule is: reading a definition back from a hand-written workflow's `# spec:` line (not only a round trip, which would let the writer and the reader share one mistake), and writing values GitHub hands to the job exactly — block scalars that keep leading spaces, blank lines and final line breaks, and `${{` escaped as probe 11 showed GitHub needs."""

from __future__ import annotations

import json
import unittest

from support.harness import engine

github = engine("claude.github")

HAND_WRITTEN = """# Written by hand for this test.
# spec: {"at": null, "cli": "/s/cli.py", "cron": "0 3 * * *", "definition": "3f9a1c2e", "effort": "high", "model": "sonnet", "name": "nightly-review", "profile": "read-only", "project": "/p", "prompt": "Review\\nyesterday", "runs_on": ["self-hosted"], "schema": null, "timeout": 3600, "timezone": "Asia/Seoul", "worktree": false}
name: claude · nightly-review
on:
  workflow_dispatch:
"""

SPEC = {"name": "nightly-review", "cron": "0 3 * * *", "at": None, "timezone": "Asia/Seoul", "profile": "read-only", "model": "sonnet", "effort": "high", "timeout": 3600, "worktree": False, "runs_on": ["self-hosted"], "project": "/Users/someone/Coding/my project", "cli": "/Users/someone/.claude/skills/claude/scripts/cli.py", "definition": "3f9a1c2e", "prompt": "Review yesterday's commits.\n", "schema": None}


class Runners(unittest.TestCase):
    """runner_problems judges the runners that can take the job — this Mac's, with every label --runs-on asks for."""

    LOCAL = [{"name": "mac", "plist": "/p", "dir": "/r", "session_create": False, "env_token": False, "path_has": {"uv": True, "claude": True, "gh": True}}]

    def kinds(self, registered, runs_on=("self-hosted",)):
        return [p["problem"] for p in github.runner_problems(registered, self.LOCAL, runs_on=runs_on)]

    def test_this_macs_runner_must_be_the_online_one(self):
        self.assertEqual(self.kinds([{"name": "mac", "status": "offline", "labels": ["self-hosted"]}, {"name": "other", "status": "online", "labels": ["self-hosted"]}]), ["offline"])
        self.assertEqual(self.kinds([{"name": "mac", "status": "online", "labels": ["self-hosted"]}]), [])

    def test_labels_must_match(self):
        registered = [{"name": "mac", "status": "online", "labels": ["self-hosted", "macOS"]}]
        self.assertEqual(self.kinds(registered, ("self-hosted", "gpu")), ["none"])
        self.assertEqual(self.kinds(registered, ("self-hosted", "macOS")), [])


class Spec(unittest.TestCase):
    def test_reads_a_hand_written_spec_line(self):
        self.assertEqual(github.parse_spec(HAND_WRITTEN), {"at": None, "cli": "/s/cli.py", "cron": "0 3 * * *", "definition": "3f9a1c2e", "effort": "high", "model": "sonnet", "name": "nightly-review", "profile": "read-only", "project": "/p", "prompt": "Review\nyesterday", "runs_on": ["self-hosted"], "schema": None, "timeout": 3600, "timezone": "Asia/Seoul", "worktree": False})
        self.assertIsNone(github.parse_spec("name: someone else's workflow\non: push\n"))
        with self.assertRaises(ValueError):
            github.parse_spec("# spec: [1, 2]\n")

    def test_round_trip(self):
        tricky = {**SPEC, "prompt": "  indented first line\n\ttab and ${{ secrets.X }} and $HOME and `ticks` and 'quotes' \"too\"\n\n한글 줄\ntrailing spaces   \n\n\n"}
        self.assertEqual(github.parse_spec(github.render_workflow(tricky)), tricky)


class Values(unittest.TestCase):
    def block(self, text, prompt):
        lines = text.split("\n")
        i = lines.index("          CLAUDE_SCHEDULE_PROMPT: " + prompt) if prompt else None
        return lines, i

    def test_prompt_block_keeps_every_character(self):
        text = github.render_workflow({**SPEC, "prompt": "  first line indented\n\nafter a blank, ${{ github.token }}\n"})
        lines = text.split("\n")
        i = lines.index("          CLAUDE_SCHEDULE_PROMPT: |2")
        self.assertEqual(lines[i + 1 : i + 4], ["              first line indented", "", "            after a blank, ${{ '${{' }} github.token }}"])

    def test_final_line_breaks_choose_the_chomping(self):
        for prompt, header in (("no newline", "|2-"), ("one\n", "|2"), ("two\n\n", "|2+")):
            with self.subTest(prompt=prompt):
                self.assertIn("          CLAUDE_SCHEDULE_PROMPT: " + header + "\n", github.render_workflow({**SPEC, "prompt": prompt}))

    def test_steps_share_flags_and_the_finish_step_alone_has_the_token(self):
        text = github.render_workflow(SPEC)
        run_line = next(l for l in text.splitlines() if l.startswith("        run: ") and " run --name " in l)
        finish_line = next(l for l in text.splitlines() if l.startswith("        run: ") and " finish --name " in l)
        self.assertEqual(run_line.replace(" run --name ", " X --name "), finish_line.replace(" finish --name ", " X --name "))
        self.assertIn("--project '/Users/someone/Coding/my project'", run_line)
        self.assertEqual(text.count("GH_TOKEN: ${{ github.token }}"), 1)
        self.assertLess(text.index("- name: Finish"), text.index("GH_TOKEN"))
        self.assertIn("permissions: {}", text)
        self.assertIn("timeout-minutes: 70", text)

    def test_a_one_off_is_a_dated_cron_with_actions_write(self):
        text = github.render_workflow({**SPEC, "cron": None, "at": "2026-11-18T15:05"})
        self.assertIn("    - cron: '5 15 18 11 *'\n      timezone: Asia/Seoul\n", text)
        self.assertIn("permissions:\n  actions: write\n", text)
        self.assertIn("--at 2026-11-18T15:05", text)

    def test_unsafe_characters_are_named(self):
        self.assertEqual(github.unsafe_text("a\x07b"), "\x07")
        self.assertIsNone(github.unsafe_text("tab\tand newline\n"))


if __name__ == "__main__":
    unittest.main()
