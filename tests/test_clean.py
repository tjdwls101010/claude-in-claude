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


class ReviewFindings(Sandbox):
    """PR 3 review: members recorded as they start (F1), clean waits for a resume holding the session (F2), exact worktree paths (F3), a worktree deleted by hand (F4), detached-HEAD commits (F5), orphans still writing (F6, F10), stop on an empty group (F7), the uncommitted count (F8), a resume line's cwd (F9)."""

    def batch_bg(self, *args):
        import subprocess, sys
        from support.harness import ENTRY
        return subprocess.Popen([sys.executable, str(ENTRY), "batch", *args], cwd=self.project, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_members_are_recorded_as_they_start(self):
        import signal, time
        proc = self.batch_bg("--group", "k", "--worktree", "--task", "a [[fake:hook_slow:4]] [[fake:sleep:20]]")
        time.sleep(1.5)
        refusal = self.cli_json("clean", "--group", "k", expect=1)
        self.assertIn("still starting", refusal["error"])
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        # The killed batch's pid may be reused by another process; that must not block clean.
        import subprocess as sp
        other = sp.Popen(["sleep", "60"])
        self.addCleanup(other.kill)
        path = self.runs_dir() / ".groups" / "k.json"
        manifest = json.loads(path.read_text())
        manifest["spawning_pid"] = other.pid
        path.write_text(json.dumps(manifest))
        members = self.cli_json("status", "--group", "k")["members"]
        self.assertTrue(members[0]["run_id"], members)
        stopped = self.cli_json("stop", "--group", "k")["stopped"]
        self.assertEqual([e["state"] for e in stopped], ["interrupted"])
        self.assertNotIn("still starting", json.dumps(self.cli_json("clean", "--group", "k", "--force")))

    def test_clean_waits_for_a_resume_that_holds_the_session(self):
        import subprocess, sys, threading, time
        from support.harness import ENTRY, engine
        reg = engine("claude.registry")
        reply = self.cli_json("batch", "--group", "h", "--worktree", "--task", "x", timeout=120)
        self.wait_state(reply["runs"][0]["run_id"])
        sid = self.status(reply["runs"][0]["run_id"])["session_id"]
        with reg.session_lock(str(self.runs_dir()), sid):
            proc = subprocess.Popen([sys.executable, str(ENTRY), "clean", "--group", "h"], cwd=self.project, env=self.env, stdout=subprocess.PIPE, text=True)
            time.sleep(1.5)
            self.assertIsNone(proc.poll(), "clean removed a worktree while a resume held its session")
        out, _ = proc.communicate(timeout=60)
        self.assertTrue(json.loads(out)["name_released"])

    def test_worktree_paths_match_exactly(self):
        reply = self.cli_json("batch", "--group", "p", "--worktree", "--task", "x", timeout=120)
        self.wait_state(reply["runs"][0]["run_id"])
        other = self.project / ".claude" / "worktrees" / "p-10"
        other.mkdir(parents=True)
        live = self.start("busy [[fake:sleep:20]]", "--cwd", str(other))
        out = self.cli_json("clean", "--group", "p")
        self.assertEqual(out["kept"], [])
        self.cli_json("stop", "--run", live["run_id"])

    def test_worktree_deleted_by_hand(self):
        user_wt = self.root / "user-wt"
        git(self.project, "worktree", "add", "-q", "-b", "userwt", str(user_wt))
        shutil.rmtree(user_wt)
        reply = self.cli_json("batch", "--group", "s", "--worktree", "--task", "x", timeout=120)
        self.wait_state(reply["runs"][0]["run_id"])
        shutil.rmtree(self.project / ".claude" / "worktrees" / "s-1")
        out = self.cli_json("clean", "--group", "s")
        self.assertTrue(out["name_released"])
        self.assertEqual(out["removed"][0].get("branch_deleted"), True, out)
        self.assertEqual(git(self.project, "branch", "--list", "--format=%(refname:short)", "worktree-s-1"), "")
        self.assertIn(str(user_wt), git(self.project, "worktree", "list"), "clean removed the record of a worktree that is not the group's")
        self.cli_json("batch", "--group", "s", "--worktree", "--task", "again", timeout=120)

    def test_commits_on_a_detached_head_are_kept(self):
        reply = self.cli_json("batch", "--group", "d", "--worktree", "--task", "x", timeout=120)
        self.wait_state(reply["runs"][0]["run_id"])
        wt = self.project / ".claude" / "worktrees" / "d-1"
        git(wt, "checkout", "-q", "--detach")
        (wt / "feat.txt").write_text("f\n")
        git(wt, "add", "feat.txt")
        git(wt, "commit", "-q", "-m", "detached work")
        for args in ((), ("--force",)):
            out = self.cli_json("clean", "--group", "d", *args)
            self.assertEqual([k["index"] for k in out["kept"]], [1], out)
            self.assertIn("detached", out["kept"][0]["reason"])
        self.assertTrue(wt.exists())
        git(wt, "branch", "saved")
        self.assertTrue(self.cli_json("clean", "--group", "d")["name_released"], "following the advice should let clean finish")
        self.assertEqual(git(self.project, "branch", "--list", "--format=%(refname:short)", "saved"), "saved")

    def test_orphan_still_writing_keeps_the_group_running_and_clean_refuses(self):
        import signal
        reply = self.cli_json("batch", "--group", "o", "--worktree", "--task", "x [[fake:sleep:25]]", timeout=120)
        run = reply["runs"][0]["run_id"]
        self.wait_for(lambda: self.status(run)["in_progress"], what="the Bash call")
        os.kill(json.loads((self.run_dir(run) / "meta.json").read_text())["supervisor_pid"], signal.SIGKILL)
        self.wait_state(run, states=("orphaned",))
        st = self.cli_json("status", "--group", "o")
        self.assertEqual((st["group_state"], st["running"], st["failed"]), ("running", [run], []))
        self.assertIn("live", self.cli_json("clean", "--group", "o", expect=1)["error"])
        import time
        began = time.time()
        header = json.loads(self.cli("result", "--group", "o", "--wait", "--wait-timeout", "3").stdout.splitlines()[0])
        self.assertGreaterEqual(time.time() - began, 2.5, "the wait returned while the member was still writing")
        self.assertEqual(header["group_state"], "running")
        self.cli_json("stop", "--group", "o")

    def test_stop_on_a_group_with_no_started_member(self):
        f = self.root / "t.jsonl"
        f.write_text(json.dumps({"prompt": "x", "kind": "resume", "resume": "00000000-0000-0000-0000-000000000000"}) + "\n")
        reply = self.cli_json("batch", "--group", "z", "--tasks-file", str(f), timeout=120)
        self.assertEqual(reply["spawned"], 0)
        self.assertEqual(self.cli_json("stop", "--group", "z"), {"stopped": []})

    def test_uncommitted_count_leaves_out_worktrees(self):
        first = self.cli_json("batch", "--group", "u", "--worktree", "--task", "x", timeout=120)
        self.wait_state(first["runs"][0]["run_id"])
        second = self.cli_json("batch", "--group", "v", "--worktree", "--task", "y", timeout=120)
        self.assertEqual(second["worktrees"]["uncommitted_in_your_tree"], 0)

    def test_resume_line_cwd_is_honoured(self):
        other = self.root / "elsewhere"
        other.mkdir()
        first = self.start("seed")
        self.wait_state(first["run_id"])
        f = self.root / "t.jsonl"
        f.write_text(json.dumps({"prompt": "again", "kind": "resume", "resume": first["run_id"], "cwd": str(other)}) + "\n")
        reply = self.cli_json("batch", "--group", "c", "--tasks-file", str(f), timeout=120)
        self.wait_state(reply["runs"][0]["run_id"])
        call = [c for c in self.fake_calls() if c["env"].get("CLAUDE_SKILL_RUN") == reply["runs"][0]["run_id"]][0]
        self.assertEqual(call["cwd"], str(other))
