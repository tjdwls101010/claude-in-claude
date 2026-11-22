"""The github unit's calls as `gh` receives them, in process against the fake gh (which reads an API path as the real one does): a workflow file's name and the branch travel percent-encoded, because gh takes the argument as a URL — on a private repository a raw `a#b.yml` wrote the file `a`, `?` became a query and `%` a parse error."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.harness import FAKE_GH_DIR, FIXTURES, engine

github = engine("claude.github")

REPO = "someone/project"


class FakeGitHub(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix="cic-gh-"))
        self.addCleanup(shutil.rmtree, self.state, ignore_errors=True)
        self.world({"auth": "ok", "repos": {REPO: {"private": True, "default_branch": "main", "files": {}, "workflows": {}}}})
        patched = mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(FAKE_GH_DIR), os.environ.get("PATH", "")]), "FAKE_GH_STATE": str(self.state), "FAKE_GH_FIXTURES": str(FIXTURES / "github")})
        patched.start()
        self.addCleanup(patched.stop)

    def world(self, data=None):
        path = self.state / "world.json"
        if data is not None:
            path.write_text(json.dumps(data))
        return json.loads(path.read_text())

    def files(self):
        return sorted(self.world()["repos"][REPO]["files"])


class Paths(FakeGitHub):
    def test_any_file_name_names_that_file(self):
        for file in ("a#b%c d.yml", "what?.yml", "261128_SS_외국인순매수.yml", "a&b=c.yml", "100%.yml", "💎 weekly.yml"):
            with self.subTest(file=file):
                github.write_workflow(REPO, file, "name: x\n", "add", "main")
                self.assertEqual(self.files(), [f".github/workflows/{file}"])
                got = github.read_workflow(REPO, file, "main")
                self.assertEqual(got["text"], "name: x\n")
                self.assertEqual(github.workflow_state(REPO, file), "active")
                github.set_workflow_enabled(REPO, file, False)
                self.assertEqual(self.world()["repos"][REPO]["workflows"], {file: "disabled_manually"})
                github.delete_workflow(REPO, file, "remove", "main", got["sha"])
                self.assertEqual(self.files(), [])

    def test_a_branch_name_is_one_query_value(self):
        w = self.world()
        w["repos"][REPO].update({"default_branch": "release&1#x", "files": {".github/workflows/ci.yml": {"text": "name: ci\n", "sha": "abc"}}})
        self.world(w)
        self.assertEqual(github.read_workflow(REPO, "ci.yml", "release&1#x")["text"], "name: ci\n")


if __name__ == "__main__":
    unittest.main()
