"""The git unit against real throwaway repositories: top level, the main checkout seen from a linked worktree, a bare repository and a submodule, and the uncommitted count."""

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


if __name__ == "__main__":
    unittest.main()
