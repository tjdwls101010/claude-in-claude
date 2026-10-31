"""Several runs as one group: starting members, what each is told, the group's result and status, worktree members (J8), and the checks a batch makes before anything starts."""

from __future__ import annotations

import json
import os

from support.harness import Sandbox, git


def worker_calls(calls):
    return [c for c in calls if "-p" in c["argv"]]


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


class Batch(Sandbox):
    def batch(self, *args, expect=0, **kw):
        return self.cli_json("batch", *args, expect=expect, timeout=120, **kw)

    def group_result(self, name, *args):
        proc = self.cli("result", "--group", name, *args, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        header, _, rest = proc.stdout.partition("\n")
        return json.loads(header), rest

    def test_members_start_and_are_collected_together(self):
        reply = self.batch("--group", "g", "--task", "one [[fake:reply:A]]", "--task", "two [[fake:reply:B]]", "--task", "three [[fake:reply:C]]")
        self.assertEqual((reply["spawned"], reply["requested"]), (3, 3))
        self.assertTrue(reply["next"]["command"].endswith("result --group g --wait"))
        self.assertEqual([r["index"] for r in reply["runs"]], [1, 2, 3])
        self.assertIn("shared_tree", reply)
        header, body = self.group_result("g", "--wait")
        self.assertEqual(header["group_state"], "completed")
        self.assertEqual(header["totals"]["completed"], 3)
        lines = body.splitlines()
        seps = [l for l in lines if l.startswith("--- [")]
        self.assertEqual(len(seps), 3)
        self.assertTrue(seps[0].startswith(f"--- [1] run={reply['runs'][0]['run_id']} state=completed bytes=1"))
        self.assertEqual(lines[lines.index(seps[1]) + 1], "B")
        prompts = sorted(c["messages"][0]["message"]["content"] for c in worker_calls(self.fake_calls()))
        self.assertTrue(all("of 3 in group g" in p for p in prompts), prompts)
        self.assertTrue(any(p.endswith("two [[fake:reply:B]]") for p in prompts))

    def test_tasks_file_with_fields_and_a_resume_round(self):
        first = self.start("seed [[fake:reply:seeded]]")
        self.wait_state(first["run_id"])
        f = self.root / "tasks.jsonl"
        f.write_text("\n".join(json.dumps(t) for t in [
            {"prompt": "fresh [[fake:reply:F]]", "label": "fresh", "profile": "read-only", "effort": "low"},
            {"prompt": "again [[fake:reply:R]]", "kind": "resume", "resume": first["run_id"], "label": "again"},
        ]) + "\n\n")
        reply = self.batch("--group", "round", "--tasks-file", str(f), "--task", "plain [[fake:reply:P]]")
        self.assertEqual([r["label"] for r in reply["runs"]], [None, "fresh", "again"])
        header, body = self.group_result("round", "--wait")
        self.assertEqual(header["group_state"], "completed")
        self.assertIn("--- [3:again]", body)
        resumed = self.status(reply["runs"][2]["run_id"])
        self.assertEqual(resumed["session_id"], first["session_id"])
        self.assertEqual(resumed["group"], "round")
        fresh = [c for c in worker_calls(self.fake_calls()) if c["env"]["CLAUDE_SKILL_RUN"] == reply["runs"][1]["run_id"]][0]
        self.assertEqual((flag_value(fresh["argv"], "--permission-mode"), flag_value(fresh["argv"], "--effort")), ("dontAsk", "low"))

    def test_invalid_batches_are_refused_before_anything_starts(self):
        f = self.root / "bad.jsonl"
        cases = [
            ["--group", "Bad Name", "--task", "x"],
            ["--group", "g"],
            ["--group", "g", "--tasks-file", str(self.root / "missing.jsonl")],
        ]
        for lines in ([{"prompt": "x", "colour": "red"}], [{"prompt": "x", "kind": "resume"}], [{"prompt": "x", "resume": "r"}], [{"label": "no prompt"}], [{"prompt": "x", "profile": "bypass"}]):
            f.write_text("\n".join(json.dumps(l) for l in lines))
            cases.append(["--group", "g", "--tasks-file", str(f)])
        for args in cases:
            with self.subTest(args):
                self.assertEqual(self.batch(*args, expect=2)["help"], "batch --help")
        f.write_text("{not json\n")
        self.batch("--group", "g", "--tasks-file", str(f), expect=2)
        self.assertEqual(worker_calls(self.fake_calls()), [])
        self.assertFalse((self.runs_dir() / ".groups" / "g.json").exists())

    def test_name_is_reserved_until_clean(self):
        self.batch("--group", "once", "--task", "x")
        self.group_result("once", "--wait")
        refused = self.batch("--group", "once", "--task", "y", expect=1)
        self.assertIn("reserved", refused["error"])
        self.assertTrue(self.cli_json("clean", "--group", "once")["name_released"])
        self.batch("--group", "once", "--task", "y")

    def test_overlaps_and_status(self):
        self.batch("--group", "ov", "--task", "a [[fake:write:same.txt]]", "--task", "b [[fake:write:same.txt]] [[fake:write:other.txt]]")
        header, _ = self.group_result("ov", "--wait")
        self.assertEqual(header["overlaps"], {str(self.project / "same.txt"): [1, 2]})
        st = self.cli_json("status", "--group", "ov")
        self.assertEqual((st["group_state"], len(st["done"]), st["running"]), ("completed", 2, []))
        listing = self.cli_json("status")
        self.assertEqual([(g["group"], g["group_state"]) for g in listing["groups"]], [("ov", "completed")])

    def test_stop_group_and_partial_state(self):
        self.batch("--group", "s", "--task", "a [[fake:sleep:30]]", "--task", "b [[fake:sleep:30]]")
        header, _ = self.group_result("s")
        self.assertEqual(header["group_state"], "running")
        self.assertIn("next", header)
        stopped = self.cli_json("stop", "--group", "s")["stopped"]
        self.assertEqual([e["state"] for e in stopped], ["interrupted", "interrupted"])
        self.assertEqual(self.cli_json("status", "--group", "s")["group_state"], "partial")

    def test_long_messages_are_cut_in_the_group_view(self):
        self.batch("--group", "long", "--task", "x [[fake:reply:" + "y" * 5000 + "]]")
        header, body = self.group_result("long", "--wait")
        m = header["members"][0]
        self.assertEqual((m["bytes"], m["shown_bytes"]), (5000, 4000))
        self.assertEqual(len(body.splitlines()[1]), 4000)

    def test_inside_a_worker(self):
        self.assertIn("worker", self.batch("--group", "w", "--task", "x", expect=1, env={"CLAUDE_SKILL_RUN": "r"})["error"])


class Worktrees(Sandbox):
    def setUp(self):
        super().setUp()
        (self.project / ".gitignore").write_text(".env\nbuild/\n")
        (self.project / ".worktreeinclude").write_text(".env\n")
        git(self.project, "add", ".gitignore", ".worktreeinclude")
        git(self.project, "commit", "-q", "-m", "ignore")
        (self.project / ".env").write_text("SECRET=1\n")
        (self.project / "dirty.txt").write_text("uncommitted\n")

    def test_writers_get_worktrees_from_local_head(self):
        head = git(self.project, "rev-parse", "HEAD")
        reply = self.cli_json("batch", "--group", "wt", "--worktree", "--task", "a", "--tasks-file", str(self._tasks([{"prompt": "b", "profile": "auto"}, {"prompt": "c", "profile": "read-only"}])), timeout=120)
        rows = reply["runs"]
        self.assertEqual([r["worktree"] is not None for r in rows], [True, True, False])
        self.assertEqual(rows[0]["worktree"], str(self.project / ".claude" / "worktrees" / "wt-1"))
        self.assertEqual(reply["worktrees"]["base"], head)
        self.assertEqual(reply["worktrees"]["uncommitted_in_your_tree"], 1, "dirty.txt; the ignored .env is not counted")
        calls = {c["env"]["CLAUDE_SKILL_RUN"]: c for c in worker_calls(self.fake_calls())}
        first = calls[rows[0]["run_id"]]
        self.assertEqual(flag_value(first["argv"], "--worktree"), "wt-1")
        self.assertEqual(json.loads(flag_value(first["argv"], "--settings"))["worktree"], {"baseRef": "head"})
        self.assertNotIn("--worktree", calls[rows[2]["run_id"]]["argv"])
        prompt = first["messages"][0]["message"]["content"]
        self.assertIn(str(self.project / ".claude" / "worktrees" / "wt-1"), prompt)
        self.assertIn(head, prompt)
        self.assertIn("1 uncommitted", prompt)
        self.assertEqual(self.wait_state(rows[0]["run_id"])["cwd"], str(self.project / ".claude" / "worktrees" / "wt-1"))
        self.assertEqual(git(self.project, "branch", "--list", "--format=%(refname:short)", "worktree-wt-1"), "worktree-wt-1")
        self.assertTrue((self.project / ".claude" / "worktrees" / "wt-1" / ".env").exists())

    def test_members_with_their_own_cwd_or_resuming_get_none(self):
        other = self.root / "other"
        other.mkdir()
        reply = self.cli_json("batch", "--group", "own", "--worktree", "--tasks-file", str(self._tasks([{"prompt": "x", "cwd": str(other)}])), timeout=120)
        self.assertIsNone(reply["runs"][0]["worktree"])
        self.assertNotIn("worktrees", reply)

    def test_a_leftover_worktree_of_the_same_name_is_refused(self):
        git(self.project, "worktree", "add", "-q", "-b", "worktree-left-1", str(self.project / ".claude" / "worktrees" / "left-1"))
        refused = self.cli_json("batch", "--group", "left", "--worktree", "--task", "x", expect=1)
        self.assertIn("left-1", refused["error"])
        self.assertEqual(worker_calls(self.fake_calls()), [])

    def _tasks(self, tasks):
        f = self.root / f"tasks-{len(list(self.root.glob('tasks-*')))}.jsonl"
        f.write_text("\n".join(json.dumps(t) for t in tasks))
        return f
