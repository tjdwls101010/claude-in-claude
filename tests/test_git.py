"""The git unit against real throwaway repositories: top level, the main checkout seen from a linked worktree, a bare repository and a submodule, the uncommitted count, and bringing a default branch up to its origin."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support.harness import engine, git, make_repo

g = engine("claude.git")


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = make_repo(self.root / "repo", {"a.txt": "a\n", "pkg/b.txt": "b\n"})

    def test_not_a_repository(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertIsNone(g.toplevel(str(plain)))
        self.assertIsNone(g.main_checkout(str(plain)))

    def test_toplevel_from_a_subdirectory(self):
        self.assertEqual(g.toplevel(str(self.repo / "pkg")), str(self.repo))
        self.assertEqual(g.main_checkout(str(self.repo / "pkg")), str(self.repo))

    def test_main_checkout_from_a_linked_worktree(self):
        wt = self.root / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "side", str(wt))
        self.assertEqual(g.toplevel(str(wt)), str(wt))
        self.assertEqual(g.main_checkout(str(wt)), str(self.repo))

    def test_bare_repository_with_a_worktree(self):
        bare = self.root / "bare.git"
        git(self.root, "clone", "-q", "--bare", str(self.repo), str(bare))
        wt = self.root / "bare-wt"
        git(bare, "worktree", "add", "-q", str(wt), "main")
        # No main checkout exists for a bare repository, so the worktree itself is where state lives.
        self.assertEqual(g.main_checkout(str(wt)), str(wt))

    def test_submodule_is_its_own_checkout(self):
        sub_src = make_repo(self.root / "subsrc")
        git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub_src), "deps/sub")
        sub = self.repo / "deps" / "sub"
        self.assertEqual(g.toplevel(str(sub)), str(sub))
        self.assertEqual(g.main_checkout(str(sub)), str(sub))

    def test_uncommitted_count(self):
        self.assertEqual(g.uncommitted_count(str(self.repo)), 0)
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("n\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "ignored.txt").write_text("i\n")
        self.assertEqual(g.uncommitted_count(str(self.repo)), 3)

    def test_head(self):
        self.assertEqual(g.head_commit(str(self.repo)), git(self.repo, "rev-parse", "HEAD"))
        empty = self.root / "empty"
        empty.mkdir()
        git(empty, "init", "-q")
        self.assertIsNone(g.head_commit(str(empty)))

    def test_paths_are_nfc(self):
        decomposed = self.root / "café"
        make_repo(decomposed)
        top = g.toplevel(str(decomposed))
        self.assertEqual(top, top.__class__(__import__("unicodedata").normalize("NFC", top)))



class Worktree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = make_repo(self.root / "repo", {"a.txt": "a\n", ".gitignore": ".env\nbuild/\n"})
        (self.repo / ".env").write_text("SECRET=1\n")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.wt = self.root / "repo" / ".claude" / "worktrees" / "g-1"
        git(self.repo, "worktree", "add", "-q", "-b", "worktree-g-1", str(self.wt), "HEAD")
        git(self.repo, "worktree", "lock", str(self.wt))
        (self.wt / ".env").write_text("SECRET=1\n")  # a .worktreeinclude copy
        (self.wt / ".claude").mkdir(exist_ok=True)
        os.symlink("/somewhere", self.wt / ".claude" / "histories")

    def test_entries(self):
        entries = {e["path"]: e for e in g.worktree_entries(str(self.repo))}
        self.assertEqual(entries[str(self.wt)]["branch"], "worktree-g-1")
        self.assertTrue(entries[str(self.wt)]["locked"])
        self.assertTrue(g.is_worktree(str(self.repo), str(self.wt)))
        self.assertFalse(g.is_worktree(str(self.repo), str(self.root)))
        self.assertTrue(g.branch_exists(str(self.repo), "worktree-g-1"))

    def test_startup_snapshot_leaves_out_include_copies(self):
        snap = g.startup_snapshot(str(self.wt), str(self.repo))
        self.assertEqual(snap, {".claude/histories": ["link", "/somewhere"]})

    def test_leftovers(self):
        snap = g.startup_snapshot(str(self.wt), str(self.repo))
        self.assertEqual(g.leftovers(str(self.wt), str(self.repo), snap), {"tracked": [], "untracked": [], "ignored": []})
        (self.wt / "a.txt").write_text("changed\n")
        (self.wt / "new" / "deep").mkdir(parents=True)
        (self.wt / "new" / "deep" / "f.txt").write_text("")
        (self.wt / "build").mkdir()
        (self.wt / "build" / "o").write_text("")
        (self.wt / ".env").write_text("SECRET=2\n")
        os.unlink(self.wt / ".claude" / "histories")
        os.symlink("/elsewhere", self.wt / ".claude" / "histories")
        left = g.leftovers(str(self.wt), str(self.repo), snap)
        self.assertEqual(left["tracked"], ["a.txt"])
        self.assertEqual(sorted(left["untracked"]), [".claude/histories", "new/deep/f.txt"])
        self.assertEqual(sorted(left["ignored"]), [".env", "build/o"])

    def test_commits_beyond_and_removal(self):
        self.assertEqual(g.commits_beyond(str(self.repo), "worktree-g-1", self.base), 0)
        (self.wt / "b.txt").write_text("b\n")
        git(self.wt, "add", "b.txt")
        git(self.wt, "commit", "-q", "-m", "b")
        self.assertEqual(g.commits_beyond(str(self.repo), "worktree-g-1", self.base), 1)
        ok, err = g.unlock_and_remove(str(self.repo), str(self.wt), force=True)
        self.assertTrue(ok, err)
        self.assertFalse(self.wt.exists())
        self.assertTrue(g.delete_branch(str(self.repo), "worktree-g-1")[0])
        self.assertFalse(g.branch_exists(str(self.repo), "worktree-g-1"))



class TreeSnapshot(unittest.TestCase):
    """What a scheduled run compares before and after the worker (K27): the branch, the commit and every changed or untracked path with its content fingerprint, and line counts against HEAD."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = make_repo(self.root / "repo", {"a.txt": "a\n", "b.txt": "b1\nb2\n"})

    def test_branch_head_and_entries(self):
        snap = g.status_snapshot(str(self.repo))
        self.assertEqual((snap["branch"], snap["head"], snap["entries"]), ("main", git(self.repo, "rev-parse", "HEAD"), {}))
        (self.repo / "a.txt").write_text("a changed\n")
        (self.repo / "new dir").mkdir()
        (self.repo / "new dir" / "n.txt").write_text("n\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "ignored.txt").write_text("i\n")
        (self.repo / ".claude" / "worktrees" / "x").mkdir(parents=True)
        (self.repo / ".claude" / "worktrees" / "x" / "f").write_text("f\n")
        snap = g.status_snapshot(str(self.repo))
        self.assertEqual(sorted(snap["entries"]), [".gitignore", "a.txt", "new dir/n.txt"])
        self.assertEqual(snap["entries"]["a.txt"]["status"], " M")
        self.assertEqual(snap["entries"]["new dir/n.txt"]["status"], "??")
        import hashlib

        self.assertEqual(snap["entries"]["a.txt"]["fingerprint"], ["file", hashlib.sha256(b"a changed\n").hexdigest()])
        (self.repo / "a.txt").unlink()
        self.assertEqual(g.status_snapshot(str(self.repo))["entries"]["a.txt"], {"status": " D", "fingerprint": ["missing", None]})

    def test_detached_head_has_no_branch(self):
        git(self.repo, "checkout", "-q", "--detach")
        self.assertIsNone(g.current_branch(str(self.repo)))
        self.assertIsNone(g.status_snapshot(str(self.repo))["branch"])
        self.assertEqual(g.current_branch(str(self.root / "repo")), None)
        git(self.repo, "checkout", "-q", "main")
        self.assertEqual(g.current_branch(str(self.repo)), "main")

    def test_not_a_repository(self):
        (self.root / "plain").mkdir()
        self.assertIsNone(g.status_snapshot(str(self.root / "plain")))
        self.assertIsNone(g.current_branch(str(self.root / "plain")))

    def test_a_project_in_a_subdirectory(self):
        import hashlib

        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "x.txt").write_text("one\n")
        git(self.repo, "add", "sub/x.txt")
        git(self.repo, "commit", "-q", "-m", "sub")
        (self.repo / "sub" / "x.txt").write_text("two\n")
        snap = g.status_snapshot(str(self.repo / "sub"))
        self.assertEqual(snap["root"], str(self.repo))
        self.assertEqual(snap["entries"]["sub/x.txt"]["fingerprint"], ["file", hashlib.sha256(b"two\n").hexdigest()])
        self.assertEqual(g.numstat(str(self.repo / "sub"), ["sub/x.txt"]), {"sub/x.txt": [1, 1]})

    def test_files_committed_between_two_commits(self):
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "a.txt").write_text("a\nmore\n")
        (self.repo / "c.txt").write_text("c1\nc2\nc3\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "work")
        head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(g.committed_files(str(self.repo), base, head), [{"status": "M", "path": "a.txt", "lines": [1, 0]}, {"status": "A", "path": "c.txt", "lines": [3, 0]}])
        self.assertEqual(g.committed_files(str(self.repo), head, head), [])

    def test_numstat_counts_staged_and_unstaged_changes_against_head(self):
        (self.repo / "a.txt").write_text("a\nmore\n")
        (self.repo / "b.txt").write_text("b1\n")
        git(self.repo, "add", "b.txt")
        self.assertEqual(g.numstat(str(self.repo), ["a.txt", "b.txt"]), {"a.txt": [1, 0], "b.txt": [0, 1]})
        self.assertEqual(g.numstat(str(self.repo), ["a.txt"]), {"a.txt": [1, 0]})
        (self.repo / "bin.dat").write_bytes(b"\x00\x01")
        git(self.repo, "add", "bin.dat")
        self.assertEqual(g.numstat(str(self.repo), ["bin.dat"]), {"bin.dat": None}, "a binary file has no line counts")
        self.assertEqual(g.numstat(str(self.repo), []), {})

if __name__ == "__main__":
    unittest.main()


class DefaultBranchSync(unittest.TestCase):
    """`sync_default` against a real bare origin: a second clone pushes what a scheduled worker would merge on GitHub, and the checkout under test is a person's, with their own edits. What is expected comes from git itself (the origin's commit, the files on disk), not from the module."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        seed = make_repo(self.root / "seed", {"a.txt": "a\n", "b.txt": "b\n", "pkg/c.txt": "c\n", ".gitignore": "secret\n"})
        self.origin = self.root / "origin.git"
        git(self.root, "clone", "-q", "--bare", str(seed), str(self.origin))
        self.local = self.clone("local")
        self.other = self.clone("other")
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def clone(self, name):
        path = self.root / name
        git(self.root, "clone", "-q", str(self.origin), str(path))
        git(path, "config", "user.email", "t@example.com")
        git(path, "config", "user.name", "t")
        return path

    def land(self, files, message, remove=()):
        """A commit on origin's main, as a merged pull request leaves one; its sha."""
        git(self.other, "pull", "-q", "--ff-only")
        for rel, text in files.items():
            p = self.other / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for rel in remove:
            git(self.other, "rm", "-q", "-r", rel)
        git(self.other, "add", "-A")
        git(self.other, "commit", "-q", "-m", message)
        git(self.other, "push", "-q", "origin", "main")
        return git(self.other, "rev-parse", "HEAD")

    def sync(self, path=None, **kw):
        return g.sync_default(str(path or self.local), env=self.env, **kw)

    def head(self, ref="HEAD"):
        return git(self.local, "rev-parse", ref)

    def test_fast_forwards_the_checked_out_default_branch(self):
        before = self.head()
        self.land({"b.txt": "b2\n"}, "first")
        sha = self.land({"new.md": "n\n"}, "second")
        r = self.sync()
        self.assertEqual((r["status"], r["files_updated"], r["branch"], r["path"]), ("updated", True, "main", str(self.local)))
        self.assertEqual((r["from"], r["to"]), (before, sha))
        self.assertEqual(self.head(), sha)
        self.assertEqual([c["subject"] for c in r["commits"]], ["second", "first"])
        self.assertEqual((self.local / "new.md").read_text(), "n\n")

    def test_already_current(self):
        r = self.sync()
        self.assertEqual(r["status"], "current")
        self.assertEqual(r["from"], r["to"])

    def test_keeps_uncommitted_changes_the_commits_do_not_touch(self):
        (self.local / "a.txt").write_text("mine\n")
        (self.local / "scratch.txt").write_text("s\n")
        sha = self.land({"b.txt": "b2\n"}, "theirs")
        self.assertEqual(self.sync()["status"], "updated")
        self.assertEqual(self.head(), sha)
        self.assertEqual((self.local / "a.txt").read_text(), "mine\n")
        self.assertEqual((self.local / "scratch.txt").read_text(), "s\n")
        self.assertEqual((self.local / "b.txt").read_text(), "b2\n")

    def test_never_over_a_changed_file(self):
        before = self.head()
        (self.local / "a.txt").write_text("mine\n")
        self.land({"a.txt": "theirs\n"}, "theirs")
        r = self.sync()
        self.assertEqual((r["status"], r["files"]), ("not_updated", ["a.txt"]))
        self.assertIn("1 file", r["reason"])
        self.assertIn("merge --ff-only origin/main", r["instead"])
        self.assertEqual(self.head(), before)
        self.assertEqual((self.local / "a.txt").read_text(), "mine\n")

    def test_never_over_an_untracked_file(self):
        before = self.head()
        (self.local / "new.md").write_text("mine\n")
        self.land({"new.md": "theirs\n"}, "theirs")
        r = self.sync()
        self.assertEqual((r["status"], r["files"]), ("not_updated", ["new.md"]))
        self.assertEqual(self.head(), before)
        self.assertEqual((self.local / "new.md").read_text(), "mine\n")

    def test_never_over_an_ignored_file(self):
        # git's default merge overwrites an ignored file with a tracked one of the same path (checked by hand); --no-overwrite-ignore keeps it.
        before = self.head()
        (self.local / "secret").write_text("LOCAL ONLY\n")
        self.land({"secret": "remote\n", ".gitignore": ""}, "track secret")
        r = self.sync()
        self.assertEqual((r["status"], r["files"]), ("not_updated", ["secret"]))
        self.assertEqual(self.head(), before)
        self.assertEqual((self.local / "secret").read_text(), "LOCAL ONLY\n")

    def test_local_commits_are_left_alone(self):
        (self.local / "a.txt").write_text("mine\n")
        git(self.local, "commit", "-q", "-am", "mine")
        mine = self.head()
        r = self.sync()
        self.assertEqual(r["status"], "not_updated")
        self.assertIn("1 commit", r["reason"])
        self.land({"b.txt": "b2\n"}, "theirs")
        r = self.sync()
        self.assertEqual(r["status"], "not_updated")
        self.assertIn("apart", r["reason"])
        self.assertEqual(self.head(), mine)

    def test_another_branch_checked_out_moves_only_the_default_branch(self):
        git(self.local, "switch", "-q", "-c", "side")
        (self.local / "a.txt").write_text("side\n")
        git(self.local, "commit", "-q", "-am", "side")
        side = self.head()
        sha = self.land({"a.txt": "theirs\n"}, "theirs")
        r = self.sync()
        self.assertEqual((r["status"], r["files_updated"]), ("ref_updated", False))
        self.assertEqual(self.head("refs/heads/main"), sha)
        self.assertEqual(self.head(), side)
        self.assertEqual((self.local / "a.txt").read_text(), "side\n")
        self.assertEqual([c["subject"] for c in r["commits"]], ["theirs"])

    def test_no_local_default_branch(self):
        git(self.local, "switch", "-q", "-c", "side")
        git(self.local, "branch", "-q", "-D", "main")
        self.land({"b.txt": "b2\n"}, "theirs")
        r = self.sync()
        self.assertEqual(r["status"], "not_updated")
        self.assertIn("no local branch main", r["reason"])

    def test_default_branch_checked_out_in_another_worktree(self):
        git(self.local, "switch", "-q", "-c", "side")
        wt = self.root / "wt"
        git(self.local, "worktree", "add", "-q", str(wt), "main")
        before = self.head("refs/heads/main")
        self.land({"b.txt": "b2\n"}, "theirs")
        r = self.sync()
        self.assertEqual(r["status"], "not_updated")
        self.assertIn("checked out", r["reason"])
        self.assertEqual(self.head("refs/heads/main"), before)

    def test_a_merge_in_progress_is_left_alone(self):
        git(self.local, "switch", "-q", "-c", "side")
        (self.local / "a.txt").write_text("side\n")
        git(self.local, "commit", "-q", "-am", "side")
        git(self.local, "switch", "-q", "main")
        (self.local / "a.txt").write_text("main\n")
        git(self.local, "commit", "-q", "-am", "main")
        git(self.local, "merge", "-q", "side", check=False)
        self.land({"b.txt": "b2\n"}, "theirs")
        r = self.sync()
        self.assertEqual(r["status"], "not_updated")
        self.assertIn("merge", r["reason"])

    def test_fetches_the_branch_by_name_whatever_the_fetch_refspec(self):
        git(self.local, "config", "remote.origin.fetch", "+refs/heads/other:refs/remotes/origin/other")
        sha = self.land({"b.txt": "b2\n"}, "theirs")
        self.assertEqual(self.sync()["status"], "updated")
        self.assertEqual(self.head(), sha)

    def test_origin_unreachable(self):
        git(self.local, "remote", "set-url", "origin", str(self.root / "gone.git"))
        r = self.sync()
        self.assertEqual(r["status"], "failed")
        self.assertIn("origin could not be read", r["reason"])

    def test_hooks_do_not_run(self):
        hook = self.local / ".git" / "hooks" / "post-merge"
        hook.write_text(f"#!/bin/sh\ntouch {self.root / 'hook-ran'}\n")
        hook.chmod(0o755)
        self.land({"b.txt": "b2\n"}, "theirs")
        self.assertEqual(self.sync()["status"], "updated")
        self.assertFalse((self.root / "hook-ran").exists())

    def test_a_subdirectory_the_update_removes(self):
        sha = self.land({}, "drop pkg", remove=("pkg",))
        r = self.sync(self.local / "pkg")
        self.assertEqual((r["status"], r["path"]), ("updated", str(self.local)))
        self.assertEqual(self.head(), sha)
        self.assertFalse((self.local / "pkg").exists())

    def test_fetch_only(self):
        before = self.head()
        sha = self.land({"b.txt": "b2\n"}, "theirs")
        r = self.sync(fetch_only=True)
        self.assertEqual((r["status"], r["to"]), ("fetched", sha))
        self.assertEqual(self.head(), before)
        self.assertEqual(self.head("refs/remotes/origin/main"), sha)

    def test_not_a_checkout(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(self.sync(plain)["status"], "failed")
