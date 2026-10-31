"""The measuring helpers other evidence rests on: `tree_snapshot` and `snapshot_diff` must catch a new file inside an existing directory, a content change, a deletion and a retargeted link, and must leave out what they are told to."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from support.harness import snapshot_diff, tree_snapshot


class TreeSnapshot(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("a = 1\n")
        (self.root / ".git").mkdir()
        (self.root / ".claude-runs").mkdir()
        os.symlink("src/a.py", self.root / "link")
        self.before = tree_snapshot(self.root)

    def test_unchanged_tree_has_no_diff(self):
        self.assertEqual(snapshot_diff(self.before, tree_snapshot(self.root)), [])

    def test_new_file_inside_an_existing_directory(self):
        (self.root / "src" / "new.py").write_text("")
        self.assertEqual(snapshot_diff(self.before, tree_snapshot(self.root)), ["src/new.py"])

    def test_content_change(self):
        (self.root / "src" / "a.py").write_text("a = 2\n")
        self.assertEqual(snapshot_diff(self.before, tree_snapshot(self.root)), ["src/a.py"])

    def test_deletion_and_link_target(self):
        os.unlink(self.root / "link")
        os.symlink("elsewhere", self.root / "link")
        (self.root / "src" / "a.py").unlink()
        self.assertEqual(snapshot_diff(self.before, tree_snapshot(self.root)), ["link", "src/a.py"])

    def test_excluded_and_allowed(self):
        (self.root / ".git" / "x").write_text("")
        (self.root / ".claude-runs" / "r").write_text("")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / ".cc-writes").mkdir()
        after = tree_snapshot(self.root)
        self.assertEqual(snapshot_diff(self.before, after), [".claude", ".claude/.cc-writes"])
        self.assertEqual(snapshot_diff(self.before, after, allowed=[".claude"]), [])


if __name__ == "__main__":
    unittest.main()
