"""The summary a scheduled run leaves on GitHub (sample B), rendered in process from a real run's events (fixture `scheduled_write.jsonl`, the plan's probe 14 run, redacted) and a hand-written meta and context, against a hand-written expected document. Subprocess tests elsewhere check only which sections appear, since a fake run's ids and times change every time."""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support.harness import FIXTURES, engine

observe = engine("claude.observe")
schedule = engine("claude.schedule")

RUN_ID = "20261117-115443-nightly-docs-756b"
SESSION = "54a91bc0-b842-4a4f-b8cc-ef2c359cea6c"
STARTED, ENDED = 1794884083.4485672, 1794884098.055107  # 11:54:43 and 11:54:58 KST
INIT = {"permission_mode": "acceptEdits", "model": "claude-haiku-5-5", "cwd": "/work/project", "claude_code_version": "2.1.326", "session_id": SESSION}


def final_message(name):
    """The worker's last text, read straight from the fixture's events."""
    text = None
    for line in (FIXTURES / name).read_text().splitlines():
        e = json.loads(line)
        if e.get("type") == "assistant":
            for b in e["message"]["content"]:
                if b.get("type") == "text":
                    text = b["text"]
    return text


class Rendered(unittest.TestCase):
    def setUp(self):
        self.reg = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.reg, ignore_errors=True)

    def run_dir(self, events="scheduled_write.jsonl", **meta):
        d = self.reg / RUN_ID
        d.mkdir()
        m = {"run_id": RUN_ID, "session_id": SESSION, "kind": "start", "label": "nightly-docs", "state": "completed", "cwd": "/work/project", "settings": {"profile": "write", "model": "haiku", "effort": "low", "schema_text": None, "timeout": 3600}, "init": INIT, "created_at": STARTED - 0.04, "started_at": STARTED, "ended_at": ENDED, "messages": [], "mode_mismatch": False, "profile_exceptions": [], "stdin_open": False}
        m.update(meta)
        (d / "meta.json").write_text(json.dumps(m))
        shutil.copy(FIXTURES / events, d / "events.jsonl")
        return observe.snapshot(cwd=str(self.reg), ref=RUN_ID, runs_dir=str(self.reg))

    def context(self, **over):
        c = {
            "name": "nightly-docs",
            "timezone": "Asia/Seoul",
            "trigger": {"kind": "dispatcher", "attempt": 1},
            "slot": 1794884040,  # 2026-11-17 11:54 KST
            "prompt": (FIXTURES / "summary" / "scheduled_write.prompt.txt").read_text(),
            "tree": {"kind": "checkout", "branch": "main", "head": "3bc9e11a0f", "uncommitted_before": 0},
            "changes": {"where": "the project checkout", "files": [{"status": " M", "path": "README.md", "lines": [1, 0]}, {"status": "??", "path": "docs/notes.md", "new_lines": 3}]},
            "continue": {"cli": "/Users/someone/.claude/skills/claude/scripts/cli.py", "project": "/work/project", "run_dir": f".claude-runs/{RUN_ID}/"},
            "log_call": f'uv run "/Users/someone/.claude/skills/claude/scripts/cli.py" log --run {RUN_ID} --project "/work/project"',
        }
        c.update(over)
        return c

    def test_sample_b(self):
        expected = (FIXTURES / "summary" / "scheduled_write.md").read_text()
        expected = expected.replace("{PROMPT}", self.context()["prompt"].rstrip("\n")).replace("{ANSWER}", final_message("scheduled_write.jsonl"))
        got = schedule.render_summary(self.run_dir(), self.context())
        self.maxDiff = None
        self.assertEqual(got, expected)

    def sections(self, text):
        marks = ["# ", "| **Run**", "[!CAUTION]", "[!WARNING]", "[!NOTE]", "<b>Prompt</b>", "---", "<b>Changes</b>", "<b>Activity</b>", "<b>Continue on your Mac</b>"]
        return [m for m in marks if m in text]

    def test_a_failure_leads_with_its_error_and_last_message(self):
        text = schedule.render_summary(self.run_dir(state="failed", error="claude exited 1: Not logged in · Please run /login"), self.context())
        self.assertTrue(text.startswith("# ❌ nightly-docs · failed\n"))
        caution = text.split("> [!CAUTION]\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("Not logged in · Please run /login", caution)
        self.assertIn("Last message: ## Probe report", caution)
        self.assertLess(text.index("[!CAUTION]"), text.index("[!WARNING]"))

    def test_cancelled_by_the_job_is_a_note_stopped_locally_is_a_caution(self):
        text = schedule.render_summary(self.run_dir(state="interrupted", error="stopped"), self.context(stopped_by_finish=True))
        self.assertTrue(text.startswith("# ⏹ nightly-docs · interrupted\n"))
        self.assertIn("**Cancelled.**", text)
        self.assertNotIn("[!CAUTION]", text)
        shutil.rmtree(self.reg / RUN_ID)
        text = schedule.render_summary(self.run_dir(state="interrupted", error="stopped"), self.context())
        self.assertIn("[!CAUTION]", text)

    def test_a_read_only_run_has_no_changes_section(self):
        text = schedule.render_summary(self.run_dir(settings={"profile": "read-only", "model": "haiku", "effort": "low", "schema_text": None, "timeout": 3600}), self.context())
        self.assertNotIn("<b>Changes</b>", text)
        self.assertEqual(self.sections(text), ["# ", "| **Run**", "[!WARNING]", "<b>Prompt</b>", "---", "<b>Activity</b>", "<b>Continue on your Mac</b>"])

    def local_row(self, text):
        return next(l for l in text.splitlines() if l.startswith("| **Local checkout** |"))

    def test_the_local_checkout_row(self):
        commit = {"sha7": "c852816", "subject": "docs: ANT *첫* 종가 [대조] (#179)"}
        cases = [
            ({"status": "updated", "branch": "main", "from": "b2bf7285d8c6", "to": "c8528163b0aa", "commits": [commit], "more": 0}, "| **Local checkout** | `main` fast-forwarded `b2bf728` → `c852816`, 1 commit from GitHub |"),
            ({"status": "ref_updated", "branch": "main", "from": "b2bf7285d8c6", "to": "c8528163b0aa", "commits": [commit], "more": 2}, "| **Local checkout** | `main` moved `b2bf728` → `c852816`, 3 commits from GitHub; another branch is checked out, so no file changed |"),
            ({"status": "current", "branch": "main", "commits": [], "more": 0}, "| **Local checkout** | `main` already matched GitHub |"),
            ({"status": "off"}, "| **Local checkout** | left as it is (`--no-pull`) |"),
            ({"status": "not_updated", "branch": "main", "reason": "you have changes to 1 file that the incoming commits also change", "files": ["README.md"], "instead": "commit, move or remove it, then `git -C /work/project merge --ff-only origin/main`"}, "| **Local checkout** | not updated from GitHub (see the warning) |"),
        ]
        for local, row in cases:
            with self.subTest(local["status"]):
                text = schedule.render_summary(self.run_dir(), self.context(local=local))
                self.assertEqual(self.local_row(text), row)
                shutil.rmtree(self.reg / RUN_ID)

    def test_commits_from_github_are_listed_as_their_text(self):
        local = {"status": "updated", "branch": "main", "from": "b2bf728", "to": "c852816", "commits": [{"sha7": "c852816", "subject": "docs: ANT *첫* 종가 [대조] (#179)"}], "more": 4}
        text = schedule.render_summary(self.run_dir(), self.context(local=local))
        block = text.split("<b>From GitHub</b>", 1)[1].split("</details>", 1)[0]
        self.assertIn(" · 5 commits now in `main` here</summary>", block)
        self.assertIn("- `c852816` docs\\: ANT \\*첫\\* 종가 \\[대조\\] \\(\\#179\\)\n", block)
        self.assertIn("- … and 4 more", block)
        self.assertLess(text.index("<b>From GitHub</b>"), text.index("<b>Changes</b>"))

    def test_a_checkout_left_behind_is_a_warning_with_what_to_run(self):
        local = {"status": "not_updated", "branch": "main", "reason": "you have changes to 1 file that the incoming commits also change", "files": ["README.md"], "instead": "commit, move or remove it, then `git -C /work/project merge --ff-only origin/main`"}
        text = schedule.render_summary(self.run_dir(), self.context(local=local))
        warning = text.split("> [!WARNING]\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("> **Your checkout was not updated from GitHub:** you have changes to 1 file that the incoming commits also change.\n> `README.md`\n> To do it yourself: commit, move or remove it, then `git -C /work/project merge --ff-only origin/main`.", warning)
        self.assertNotIn("<b>From GitHub</b>", text)

    def test_schema_answer_is_a_json_block_and_missing_json_is_red(self):
        schema = {"profile": "read-only", "model": "haiku", "effort": "low", "schema_text": '{"type": "object"}', "timeout": None}
        text = schedule.render_summary(self.run_dir("schema.jsonl", settings=schema, init=None), self.context())
        self.assertIn("\n```json\n", text)
        shutil.rmtree(self.reg / RUN_ID)
        text = schedule.render_summary(self.run_dir(settings=schema), self.context())
        self.assertTrue(text.startswith("# ❌ nightly-docs · completed without structured output\n"), text[:80])

    def test_a_worktree_run_says_where_it_worked_and_what_was_kept(self):
        tree = {"kind": "worktree", "path": "/work/project/.claude/worktrees/nightly-docs-9-1-1", "branch": "worktree-nightly-docs-9-1-1", "base": "3bc9e11a0f"}
        changes = {"where": "the worktree", "kind": "worktree", "files": [{"status": "??", "path": "docs/notes.md", "new_lines": 3}], "kept": {"path": tree["path"], "branch": tree["branch"], "clean": "uv run … clean --group nightly-docs-9-1"}}
        text = schedule.render_summary(self.run_dir(), self.context(tree=tree, changes=changes))
        self.assertIn("worktree `/work/project/.claude/worktrees/nightly-docs-9-1-1` on `worktree-nightly-docs-9-1-1` from `3bc9e11`", text)
        self.assertIn("The worktree is kept because it holds these changes", text)
        self.assertNotIn("What another process changed", text)

    def test_no_worker_skipped_check_and_refused(self):
        skipped = schedule.render_summary(None, self.context(outcome={"kind": "skipped", "reason": "this slot already ran", "previous": {"url": "https://github.com/someone/project/actions/runs/1", "state": "completed"}}, at=STARTED))
        self.assertTrue(skipped.startswith("# ⏭ nightly-docs · skipped\n"))
        self.assertIn("[the earlier run](https://github.com/someone/project/actions/runs/1) (completed)", skipped)
        self.assertNotIn("<b>Activity</b>", skipped)
        check = schedule.render_summary(None, self.context(trigger={"kind": "manual", "attempt": 1}, slot=None, outcome={"kind": "check", "ok": False, "checks": [{"name": "login", "ok": False, "detail": "claude is not logged in (authMethod none)"}, {"name": "uv", "ok": True, "detail": "/Users/someone/.local/bin/uv"}]}, at=STARTED, prompt=None))
        self.assertTrue(check.startswith("# 🔎 nightly-docs · check failed\n"))
        self.assertIn("| **login** | ❌ claude is not logged in (authMethod none) |", check)
        self.assertIn("[!CAUTION]", check)
        refused = schedule.render_summary(None, self.context(outcome={"kind": "refused", "title": "not started", "error": "--worktree needs a commit to start from; this repository has none"}, at=STARTED))
        self.assertTrue(refused.startswith("# ❌ nightly-docs · not started\n"))
        self.assertIn("--worktree needs a commit", refused)

    def test_counts_and_small_costs_read_right(self):
        snap = self.run_dir()
        snap["header"]["tool_calls"] = {"Bash": 1}
        snap["header"]["cost_usd"] = 0.0031
        snap["header"]["profile_exceptions"] = [{"setting": "permissions.allow WebFetch(domain:…)", "file": "/h/.claude/settings.json", "value": ["github.com"], "effect": "x"}]
        snap["rows"] = [r for r in snap["rows"] if r["kind"] != "bash" or r["detail"].startswith("ls")]
        snap["rows"] = [r for r in snap["rows"] if r["kind"] in ("bash", "result", "init", "ratelimit", "msg")]
        text = schedule.render_summary(snap, self.context())
        self.assertIn("· 1 tool call · <$0.01 |", text)
        self.assertIn("<b>Activity</b> · 1 tool call</summary>", text)
        self.assertIn("**1 setting in your Claude Code files widens the `write` profile:**", text)

    def test_a_job_without_a_worker_says_when_it_ran_not_started(self):
        text = schedule.render_summary(None, self.context(outcome={"kind": "skipped", "reason": "this slot already ran", "previous": {}}, at=STARTED))
        self.assertIn("| **Trigger** | dispatcher · slot 2026-11-17 11:54 KST · at 11:54:43 |", text)

    def test_a_huge_intermediate_message_keeps_the_summary_whole(self):
        snap = self.run_dir()
        snap["rows"].insert(3, {"kind": "msg", "index": 20, "time": None, "text": "y" * 1_000_000})
        text = schedule.render_summary(snap, self.context())
        self.assertLess(len(text.encode()), 900_000)
        self.assertEqual(text.count("<details"), text.count("</details>"))
        self.assertIn("<b>Continue on your Mac</b>", text)

    def test_table_cells_and_lists_escape_what_they_must(self):
        snap = self.run_dir()
        snap["rows"] += [{"kind": "task", "index": 90, "time": None, "status": "started", "description": "split a | b"}, {"kind": "retry", "index": 91, "time": None, "attempt": 1, "max_retries": 3, "error": "x | y", "error_status": 529}]
        snap["header"]["permission_denials"] = [{"tool": "Bash", "input": '{"command": "cat a | grep b"}'}]
        text = schedule.render_summary(snap, self.context())
        for line in text.splitlines():
            if line.startswith("| ") and ("task" in line or "retry" in line) and "Step" not in line:
                self.assertEqual(line.replace("\\|", "").count("|"), 6, line)
        self.assertIn("> - `Bash` `cat a | grep b`", text)

    def test_a_huge_change_list_keeps_the_summary_whole(self):
        files = [{"status": "??", "path": f"generated/{'d' * 60}/file-{n:05d}.txt", "new_lines": 1} for n in range(12000)]
        text = schedule.render_summary(self.run_dir(), self.context(changes={"where": "the project checkout", "files": files}))
        self.assertLess(len(text.encode()), 900_000)
        self.assertEqual(text.count("<details"), text.count("</details>"))
        self.assertIn("<b>Continue on your Mac</b>", text)
        self.assertIn("12000 files changed during the run", text)

    def test_every_section_at_its_limit_still_fits(self):
        files = [{"status": "??", "path": "p/" + "e" * 975 + f"{n:03d}", "new_lines": 1} for n in range(500)]
        snap = self.run_dir()
        snap["text"] = "a" * 400_000
        text = schedule.render_summary(snap, self.context(prompt="b" * 50_000, changes={"where": "the project checkout", "files": files}))
        self.assertLess(len(text.encode()), 900_000)
        self.assertEqual(text.count("<details"), text.count("</details>"))
        self.assertIn("<b>Continue on your Mac</b>", text)

    def test_a_long_list_of_edited_files_outside_git_fits(self):
        edited = ["/work/project/" + "f" * 960 + f"{n:04d}" for n in range(1000)]
        text = schedule.render_summary(self.run_dir(), self.context(changes={"where": "the project directory", "not_git": edited, "files": []}))
        self.assertLess(len(text.encode()), 900_000)
        self.assertEqual(text.count("<details"), text.count("</details>"))
        self.assertIn("<b>Continue on your Mac</b>", text)

    def test_a_name_shows_in_the_title_as_its_characters(self):
        # A name is the person's and may hold what markdown reads as emphasis, a link, a tag, an autolink or math. The title is the markdown that was sent to GitHub's renderer (fixture .md), and the fixture .html is what came back.
        name = "_a_ *b* [c](x) <e> @octocat #1 www.x.com $a$ ~s~ `t` &amp; 1. x! \"q\" 'r' {k} a|b c\\d e^f g=h i+j k;l m:n o/p q?r 100% nightly-docs"
        text = schedule.render_summary(self.run_dir(), self.context(name=name))
        self.assertEqual(text.splitlines()[0] + "\n", (FIXTURES / "summary" / "title-escaped.md").read_text())
        shown = (FIXTURES / "summary" / "title-escaped.html").read_text()
        self.assertEqual(html.unescape(re.sub(r"<[^>]+>", "", shown)).strip(), f"✅ {name} · completed", "GitHub showed the name's own characters")
        self.assertEqual(set(re.findall(r"<(\w[\w-]*)", shown)), {"h1", "span", "a"}, "and made nothing of them but the spans around `$` and a link")
        self.assertEqual(re.findall(r"<a [^>]*>([^<]*)</a>", shown), ["@octocat"], "a mention is still linked; its text is unchanged")

    def test_every_kind_of_title_writes_the_name_the_same_way(self):
        for outcome, title in (({"kind": "skipped", "reason": "this slot already ran", "previous": {}}, "# ⏭ 261128\\_SS\\_외국인순매수 · skipped"), ({"kind": "check", "ok": True, "checks": []}, "# 🔎 261128\\_SS\\_외국인순매수 · check passed"), ({"kind": "refused", "title": "not started", "error": "x"}, "# ❌ 261128\\_SS\\_외국인순매수 · not started")):
            text = schedule.render_summary(None, self.context(name="261128_SS_외국인순매수", outcome=outcome, at=STARTED))
            self.assertEqual(text.splitlines()[0], title)
        failed = schedule.render_summary(self.run_dir(state="failed", error="x"), self.context(name="a*b"))
        self.assertEqual(failed.splitlines()[0], "# ❌ a\\*b · failed")

    def test_inline_code_outlasts_any_run_of_backticks(self):
        text = schedule.render_summary(self.run_dir(), self.context(tree={"kind": "checkout", "branch": "fix``x`y", "head": "abc1234", "uncommitted_before": 0}))
        row = next(l for l in text.splitlines() if l.startswith("| **Local tree**"))
        self.assertIn("``` fix``x`y ``` @ `abc1234`", row)

    def test_table_rows_escape_pipes_in_branch_names(self):
        text = schedule.render_summary(self.run_dir(), self.context(tree={"kind": "checkout", "branch": "fix|x", "head": "abc1234", "uncommitted_before": 0}))
        row = next(l for l in text.splitlines() if l.startswith("| **Local tree**"))
        self.assertEqual(row.replace("\\|", "").count("|"), 3, row)

    def test_limits_cut_the_answer_and_the_prompt(self):
        big = "x" * 500_000
        text = schedule.render_summary(self.run_dir(), self.context(prompt=big))
        self.assertLess(len(text.encode()), 900_000)
        self.assertIn("The prompt cut at", text)


if __name__ == "__main__":
    unittest.main()
