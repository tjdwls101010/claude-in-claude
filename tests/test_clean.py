"""`clean` (J9) and resuming a worktree member (J17): what may be removed without --force, what is kept and why, branches, live members, and a worktree that is gone or not re-entered."""

from __future__ import annotations

import json
import os
import shutil

from support.harness import FAST_TIMINGS, Sandbox, git


class Clean(Sandbox):
    def setUp(self):
        super().setUp()
        (self.project / ".gitignore").write_text(".env\nbuild/\n")
        (self.project / ".worktreeinclude").write_text(".env\n")
        git(self.project, "add", ".gitignore", ".worktreeinclude")
        git(self.project, "commit", "-q", "-m", "ignore")
        (self.project / ".env").write_text("SECRET=1\n")
        self.env["FAKE_CLAUDE_STARTUP_LINK"] = "1"

    def batch(self, name, *prompts):
        args = ["batch", "--group", name, "--worktree"]
        for p in prompts:
            args += ["--task", p]
        reply = self.cli_json(*args, timeout=120)
        for r in reply["runs"]:
            self.wait_state(r["run_id"], timeout=30)
        return reply

    def wt(self, name):
        return self.project / ".claude" / "worktrees" / name

    def clean(self, name, *args, expect=0):
        return self.cli_json("clean", "--group", name, *args, expect=expect, timeout=120)

    def test_untouched_worktree_goes_without_force(self):
        reply = self.batch("ok", "look only [[fake:ccwrites]]")
        self.assertTrue((self.wt("ok-1") / ".claude" / "histories").is_symlink())
        self.assertTrue((self.wt("ok-1") / ".env").exists())
        meta = self.status(reply["runs"][0]["run_id"])
        self.assertEqual(meta["cwd"], str(self.wt("ok-1")))
        out = self.clean("ok")
        self.assertEqual(out["kept"], [])
        self.assertEqual([r["branch_deleted"] for r in out["removed"]], [True])
        self.assertTrue(out["name_released"])
        self.assertFalse(self.wt("ok-1").exists())
        self.assertEqual(git(self.project, "branch", "--list", "--format=%(refname:short)", "worktree-ok-1"), "")

    def test_worker_files_are_kept_until_force(self):
        self.batch("keep", "x [[fake:write:new.txt]]", "y [[fake:write:.env]]", "z [[fake:write:build/out.o]]", "w [[fake:write:deep/er/file.txt]]")
        out = self.clean("keep")
        self.assertFalse(out["name_released"])
        kept = {k["index"]: k for k in out["kept"]}
        self.assertEqual(sorted(kept), [1, 2, 3, 4])
        self.assertEqual(kept[1]["untracked"], ["new.txt"])
        self.assertIn(".env", kept[2]["ignored_top"], "a changed .worktreeinclude copy is the worker's")
        self.assertEqual(kept[3]["ignored_top"], ["build"])
        self.assertEqual(kept[4]["untracked"], ["deep/er/file.txt"])
        for i in range(1, 5):
            self.assertTrue(self.wt(f"keep-{i}").exists())
        forced = self.clean("keep", "--force")
        self.assertTrue(forced["name_released"])
        self.assertEqual(len(forced["removed"]), 4)

    def test_a_later_init_does_not_turn_worker_files_into_startup_artifacts(self):
        reply = self.cli_json("batch", "--group", "late", "--worktree", "--task", "x [[fake:write:made.txt]] [[fake:sleep:10]]", timeout=120)
        run = reply["runs"][0]["run_id"]
        self.cli_json("send", run, "stop and summarise", "--interrupt")
        self.wait_state(run)
        again = self.cli_json("resume", run, "one more look")
        self.assertEqual(self.wait_state(again["run_id"])["state"], "completed")
        out = self.clean("late")
        self.assertEqual([k["untracked"] for k in out["kept"]], [["made.txt"]])

    def test_branch_with_commits_is_never_deleted(self):
        self.batch("cm", "x [[fake:write:feature.txt]] [[fake:commit:add feature]]")
        out = self.clean("cm")
        self.assertEqual(out["kept"], [])
        self.assertEqual(out["removed"][0]["branch_kept"], "worktree-cm-1")
        self.assertEqual(git(self.project, "branch", "--list", "--format=%(refname:short)", "worktree-cm-1"), "worktree-cm-1")

    def test_live_member_refuses(self):
        reply = self.cli_json("batch", "--group", "busy", "--worktree", "--task", "x [[fake:sleep:30]]", timeout=120)
        refusal = self.clean("busy", expect=1)
        self.assertIn("live", refusal["error"])
        self.assertTrue(refusal["instead"].endswith("stop --group busy"))
        self.clean("busy", "--force", expect=1)
        self.assertTrue(self.wt("busy-1").exists())
        self.cli_json("stop", "--group", "busy")

    def test_group_without_worktrees_just_releases(self):
        self.cli_json("batch", "--group", "plain", "--task", "x", timeout=120)
        self.cli("result", "--group", "plain", "--wait")
        self.assertEqual(self.clean("plain"), {"group": "plain", "removed": [], "kept": [], "name_released": True})


class ResumeWorktreeMember(Sandbox):
    def setUp(self):
        super().setUp()
        reply = self.cli_json("batch", "--group", "m", "--worktree", "--task", "first [[fake:write:a.txt]]", timeout=120)
        self.run_id = reply["runs"][0]["run_id"]
        self.wait_state(self.run_id)
        self.path = self.project / ".claude" / "worktrees" / "m-1"

    def test_resume_goes_back_into_the_worktree(self):
        again = self.cli_json("resume", self.run_id, "continue")
        self.assertEqual(again["cwd"], str(self.path))
        self.assertEqual(self.wait_state(again["run_id"])["state"], "completed")
        call = [c for c in self.fake_calls() if c["env"].get("CLAUDE_SKILL_RUN") == again["run_id"]][0]
        self.assertEqual(call["cwd"], str(self.project), "resume runs from where the member was launched; Claude Code re-enters the worktree")
        self.assertIn(str(self.path), call["messages"][0]["message"]["content"])

    def test_gone_worktree_refuses_resume(self):
        git(self.project, "worktree", "remove", "--force", "--force", str(self.path))
        refusal = self.cli_json("resume", self.run_id, "continue", expect=1)
        self.assertIn("gone", refusal["error"])
        self.assertIn(" start ", refusal["instead"])

    def test_init_elsewhere_is_a_cwd_mismatch(self):
        again = self.cli_json("resume", self.run_id, f"continue [[fake:cwd:{self.project}]] [[fake:sleep:10]]", expect=0)
        row = self.wait_state(again["run_id"], timeout=30)
        self.assertEqual(row["state"], "failed")
        self.assertIn("cwd_mismatch", row["error"])
        self.assertIn("SessionStart", row["error"])
