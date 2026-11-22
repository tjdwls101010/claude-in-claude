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


class Listing(FakeGitHub):
    """The workflow directory as one GraphQL call gives it. The answers' shapes are captures (fixtures graphql-*.json): entries of a tree with each blob's text, `object: null` when the directory is not there, and `data.repository: null` with an error when gh cannot see the repository."""

    def put(self, **files):
        w = self.world()
        w["repos"][REPO]["files"] = {f".github/workflows/{k}": ({"text": v, "sha": "abc"} if isinstance(v, str) else {"sha": "abc", **v}) for k, v in files.items()}
        self.world(w)

    def test_every_entry_with_the_text_of_the_workflow_files(self):
        self.put(**{"ci.yml": "name: ci\n", "261128_SS_외국인순매수.yml": "name: 한글\n", "notes.txt": "not a workflow\n", "old.yaml": "name: old\n", "sub/keep.yml": "nested\n"})
        self.assertEqual(github.list_workflow_files(REPO, "main"), [
            {"file": "261128_SS_외국인순매수.yml", "kind": "blob", "text": "name: 한글\n"},
            {"file": "ci.yml", "kind": "blob", "text": "name: ci\n"},
            {"file": "notes.txt", "kind": "blob", "text": None},
            {"file": "old.yaml", "kind": "blob", "text": "name: old\n"},
            {"file": "sub", "kind": "tree", "text": None},
        ])

    def test_no_directory_is_no_files(self):
        self.assertEqual(github.list_workflow_files(REPO, "main"), [])

    def test_a_body_graphql_did_not_bring_whole_is_read_on_its_own(self):
        self.put(**{"binaryish.yml": {"text": "name: a\n# rest\n", "graphql": "none"}, "long.yml": {"text": "name: b\n" + "# pad\n" * 50, "graphql": "truncated"}})
        got = {f["file"]: f["text"] for f in github.list_workflow_files(REPO, "main")}
        self.assertEqual(got, {"binaryish.yml": "name: a\n# rest\n", "long.yml": "name: b\n" + "# pad\n" * 50})

    def test_a_repository_gh_cannot_see(self):
        with self.assertRaises(github.GitHubError) as cm:
            github.list_workflow_files("someone/none", "main")
        self.assertIn("Could not resolve to a Repository", cm.exception.message)
        self.assertEqual(cm.exception.status, 404)

    def test_states_of_more_workflows_than_one_page(self):
        w = self.world()
        w["repos"][REPO]["workflows"] = {**{f"build-{n:03d}.yml": "active" for n in range(150)}, "z#last.yml": "disabled_manually"}
        self.world(w)
        states = github.workflow_states(REPO)
        self.assertEqual(len(states), 151)
        self.assertEqual((states["build-000.yml"], states["z#last.yml"]), ("active", "disabled_manually"))

    def test_a_directory_where_a_file_was_asked_for_has_no_text(self):
        self.put(**{"nightly.yml/inner.yml": "x\n"})
        self.assertEqual(github.read_workflow(REPO, "nightly.yml", "main")["text"], None)


if __name__ == "__main__":
    unittest.main()
