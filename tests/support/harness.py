"""Scaffolding shared by every test: a throwaway project, the fake `claude` first on PATH, a private HOME, and the CLI driven as a subprocess.

The CLI is the main seam because what is under test includes detached supervisors, process groups and signals, none of which survive being faked in-process. Pure units are imported through `engine`, which hands back only a unit's interface.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO / ".claude" / "skills" / "claude"
# The one place the entry point is named. CLAUDE_SKILL_TEST_ENTRY points the suite at another copy of the scripts, which is how a deliberately broken engine is shown to turn tests red without touching the real one.
ENTRY = Path(os.environ.get("CLAUDE_SKILL_TEST_ENTRY") or SKILL_DIR / "scripts" / "cli.py")
SCRIPTS = ENTRY.parent
SUPPORT = Path(__file__).resolve().parent
FAKE_DIR = SUPPORT / "fake_claude"
FIXTURES = SUPPORT / "fixtures"

TERMINAL = ("completed", "failed", "interrupted", "timed_out", "orphaned")
# Short timings so lifecycle tests do not wait out production grace periods; the skill reads this one variable and nothing else changes.
FAST_TIMINGS = {"idle_grace": 0.6, "init_wait": 8, "send_wait": 5, "stop_grace": 2, "finishing_attention": 2, "retry_attention": 2, "stall": 3, "poll": 0.05}


def _load_package():
    """Load the skill's package from the scripts under test without touching sys.path, the way `cli.py` sees it."""
    if "claude" in sys.modules and getattr(sys.modules["claude"], "__file__", "").startswith(str(SCRIPTS)):
        return
    spec = importlib.util.spec_from_file_location("claude", SCRIPTS / "claude" / "__init__.py", submodule_search_locations=[str(SCRIPTS / "claude")])
    module = importlib.util.module_from_spec(spec)
    sys.modules["claude"] = module
    spec.loader.exec_module(module)


def engine(unit):
    """A unit's interface (`"claude.runs"`, `"claude.claude_cli"`, …) as a namespace holding only what the unit offers, so a test cannot reach past it."""
    _load_package()
    parts = unit.split(".")
    if len(parts) != 2 or parts[0] != "claude":
        raise ValueError(f"engine takes a unit, not {unit!r}")
    module = importlib.import_module(unit)
    names = getattr(module, "__all__", None)
    if names is None:
        names = [n for n in vars(module) if not n.startswith("_") and not isinstance(getattr(module, n), types.ModuleType)]
    return types.SimpleNamespace(**{n: getattr(module, n) for n in names})


def git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    if check and proc.returncode:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


def make_repo(path, files=None):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    for rel, text in (files or {"README.md": "hi\n"}).items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


def tree_snapshot(root, exclude=(".git", ".claude-runs")):
    """Every entry under `root` except the excluded top-level names, as relative path → (kind, sha256 for a file, target for a link)."""
    import hashlib

    out = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in exclude]
            filenames = [f for f in filenames if f not in exclude]
        for d in list(dirnames):
            p = Path(dirpath) / d
            rel = str(rel_dir / d)
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
                dirnames.remove(d)
            else:
                out[rel] = ("dir", None)
        for f in filenames:
            p = Path(dirpath) / f
            rel = str(rel_dir / f)
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            else:
                out[rel] = ("file", hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def snapshot_diff(before, after, allowed=()):
    """Entries added, removed or changed between two snapshots, leaving out the paths in `allowed` and anything under them."""

    def free(path):
        return not any(path == a or path.startswith(a.rstrip("/") + "/") for a in allowed)

    changed = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path) and free(path):
            changed.append(path)
    return changed


class Sandbox(unittest.TestCase):
    """A test case with a fresh project, a private HOME and the fake claude on PATH. `self.cli(...)` runs the skill's entry point."""

    git_project = True
    fake_version = "2.1.314"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="cic-")).resolve()
        self.addCleanup(self._teardown)
        self.home = self.root / "home"
        self.home.mkdir()
        self.state = self.root / "fake-state"
        self.state.mkdir()
        self.project = self.root / "project"
        if self.git_project:
            make_repo(self.project)
        else:
            self.project.mkdir()
        self.env = {
            "PATH": f"{FAKE_DIR}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(self.home),
            "FAKE_CLAUDE_STATE": str(self.state),
            "FAKE_CLAUDE_VERSION": self.fake_version,
            "FAKE_CLAUDE_FIXTURES": str(FIXTURES),
            "CLAUDE_SKILL_TEST_TIMINGS": json.dumps(FAST_TIMINGS),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C.UTF-8",
        }
        for key in ("TMPDIR", "UV_CACHE_DIR"):
            if key in os.environ:
                self.env[key] = os.environ[key]

    def _teardown(self):
        # Kill whatever fake processes a failing test left behind, then remove the tree.
        for meta in self.root.rglob("meta.json"):
            try:
                m = json.loads(meta.read_text())
            except (OSError, ValueError):
                continue
            for key in ("claude_pgid",):
                pgid = m.get(key)
                if pgid:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
            pid = m.get("supervisor_pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        shutil.rmtree(self.root, ignore_errors=True)

    def cli(self, *args, cwd=None, input=None, env=None, timeout=60):
        proc = subprocess.run([sys.executable, str(ENTRY), *args], cwd=cwd or self.project, input=input, capture_output=True, text=True, env={**self.env, **(env or {})}, timeout=timeout)
        return proc

    def cli_json(self, *args, expect=0, **kw):
        proc = self.cli(*args, **kw)
        self.assertEqual(proc.returncode, expect, f"exit {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
        lines = proc.stdout.strip().splitlines()
        self.assertTrue(lines, f"no stdout; stderr: {proc.stderr}")
        return json.loads(lines[0])

    def start(self, prompt, *args, **kw):
        return self.cli_json("start", prompt, *args, **kw)

    def status(self, run_id, **kw):
        return self.cli_json("status", "--run", run_id, **kw)

    def wait_state(self, run_id, states=TERMINAL, timeout=30, **kw):
        end = time.time() + timeout
        row = None
        while time.time() < end:
            row = self.status(run_id, **kw)
            if row["state"] in states:
                return row
            time.sleep(0.1)
        self.fail(f"run {run_id} never reached {states}; last row {json.dumps(row)[:800]}")

    def wait_for(self, predicate, timeout=20, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def fake_calls(self):
        """Every invocation the fake recorded: argv, cwd, env and the stdin messages it read, oldest first."""
        calls = []
        for path in sorted((self.state / "calls").glob("*.json"), key=lambda p: p.stat().st_mtime_ns) if (self.state / "calls").exists() else []:
            try:
                calls.append(json.loads(path.read_text()))
            except ValueError:
                pass
        return calls

    def runs_dir(self, project=None):
        return Path(project or self.project) / ".claude-runs"

    def run_dir(self, run_id, project=None):
        return self.runs_dir(project) / run_id

    def events(self, run_id, project=None):
        path = self.run_dir(run_id, project) / "events.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
