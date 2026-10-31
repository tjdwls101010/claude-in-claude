"""The skill's tree is a contract: two top-level names under scripts/, units of four kinds importing one way, nothing reaching past a unit's interface, and nothing editing sys.path.

The checks run over a root directory, so the same functions are pointed once at a synthetic tree with planted violations to show they catch them.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support.harness import REPO, SCRIPTS

PACKAGE = "claude"

# Every unit directly in the package, by kind. A new module or subpackage must be added here, so its kind is a decision.
KINDS = {
    "runs": "feature",
    "batch": "feature",
    "observe": "feature",
    "doctor": "feature",
    "registry": "store",
    "claude_cli": "system",
    "git": "system",
    "errors": "shared",
    "util": "shared",
}
# A unit may import a unit of a lower layer. Features may import each other only along FEATURE_EDGES.
LAYER = {"feature": 3, "store": 2, "system": 1, "shared": 0}
FEATURE_EDGES = {("batch", "runs")}


def unit_of(dotted):
    """`claude.runs.create` → `runs`; `claude` → None."""
    parts = dotted.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == PACKAGE else None


def module_name(scripts, path):
    rel = path.relative_to(scripts).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports(path, scripts=None):
    """`(line, dotted module, imported names or None)` for every import in a file, relative imports resolved against the file's own package when `scripts` is given."""
    tree = ast.parse(path.read_text(), str(path))
    here = module_name(scripts, path).split(".") if scripts else []
    is_pkg = path.name == "__init__.py"
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name, None))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                pkg = here if is_pkg else here[:-1]
                pkg = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                base = ".".join(pkg + ([base] if base else []))
            out.append((node.lineno, base, [a.name for a in node.names]))
    return out


def interface(scripts, unit):
    """The names a unit offers: a subpackage's literal `__all__`, or a module's public top-level names."""
    pkg = scripts / PACKAGE / unit
    if pkg.is_dir():
        tree = ast.parse((pkg / "__init__.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
                return set(ast.literal_eval(node.value))
        return set()
    tree = ast.parse((scripts / PACKAGE / f"{unit}.py").read_text())
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {n for n in names if not n.startswith("_")}


def layout_violations(scripts):
    wrong = []
    top = {p.name for p in scripts.iterdir() if p.name != "__pycache__"}
    if top != {"cli.py", PACKAGE}:
        wrong.append(f"scripts/ holds {sorted(top)}, not exactly cli.py and {PACKAGE}/")
    pkg = scripts / PACKAGE
    if not (pkg / "__init__.py").is_file():
        wrong.append(f"{PACKAGE}/__init__.py is missing")
    for p in pkg.iterdir():
        if p.name in ("__init__.py", "__pycache__"):
            continue
        name = p.stem if p.suffix == ".py" else p.name
        if name not in KINDS:
            wrong.append(f"{p.name} has no kind in KINDS")
        if p.is_dir() and not (p / "__init__.py").is_file():
            wrong.append(f"{p.name}/ has no __init__.py")
    for unit in KINDS:
        if not ((pkg / unit).is_dir() or (pkg / f"{unit}.py").is_file()):
            wrong.append(f"KINDS names {unit}, which does not exist")
    return wrong


def skill_files(scripts):
    return sorted(p for p in scripts.rglob("*.py") if "__pycache__" not in p.parts)


def direction_violations(scripts):
    """Imports inside the package that go up a layer, sideways between units off FEATURE_EDGES, or anywhere into cli."""
    wrong = []
    for path in skill_files(scripts):
        if path.name == "cli.py" and path.parent == scripts:
            continue
        me = unit_of(module_name(scripts, path))
        for line, mod, _ in imports(path, scripts):
            other = unit_of(mod)
            if mod == "cli" or mod.startswith("cli."):
                wrong.append(f"{path.relative_to(scripts)}:{line} imports cli")
            if me is None or other is None or other == me:
                continue
            a, b = KINDS.get(me), KINDS.get(other)
            if a is None or b is None:
                continue
            if a == b == "feature":
                if (me, other) not in FEATURE_EDGES:
                    wrong.append(f"{path.relative_to(scripts)}:{line} {me} → {other} is not a feature edge")
            elif LAYER[a] <= LAYER[b]:
                wrong.append(f"{path.relative_to(scripts)}:{line} {a} {me} imports {b} {other}")
    return wrong


def reach_violations(scripts, files, *, inside_package):
    """Imports that reach past a unit's interface: a module inside a unit, a name the unit does not offer, or the bare package or unit bound as a name."""
    wrong = []
    for path in files:
        me = unit_of(module_name(scripts, path)) if inside_package else None
        for line, mod, names in imports(path, scripts if inside_package else None):
            parts = mod.split(".")
            if parts[0] != PACKAGE:
                continue
            other = unit_of(mod)
            where = f"{path.relative_to(path.parents[1] if not inside_package else scripts)}:{line}"
            if other is not None and other == me:
                continue
            if names is None:
                wrong.append(f"{where} `import {mod}` binds the package; import names from a unit")
                continue
            if other is None:
                wrong.append(f"{where} `from {PACKAGE} import {', '.join(names)}` binds a unit as a name")
                continue
            if len(parts) > 2:
                wrong.append(f"{where} reaches inside {other}: {mod}")
                continue
            offered = interface(scripts, other)
            for n in names:
                if n not in offered:
                    wrong.append(f"{where} {other} does not offer {n}")
    return wrong


SYS_PATH_READS = {"index", "count", "copy", "__contains__", "__iter__", "__len__", "__getitem__"}


def sys_path_changes(path):
    """Lines that change sys.path: a method call other than a read, any assignment or deletion that targets it, or `from sys import path`."""
    tree = ast.parse(path.read_text())
    sys_names = {"sys"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "sys" and a.asname:
                    sys_names.add(a.asname)
    lines = []

    def is_sys_path(n):
        return isinstance(n, ast.Attribute) and n.attr == "path" and isinstance(n.value, ast.Name) and n.value.id in sys_names

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sys" and any(a.name == "path" for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and is_sys_path(node.func.value) and node.func.attr not in SYS_PATH_READS:
            lines.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for t in targets:
                for sub in ast.walk(t):
                    if is_sys_path(sub):
                        lines.append(node.lineno)
    return lines


def test_files():
    return sorted(p for p in (REPO / "tests").rglob("*.py") if "__pycache__" not in p.parts)


class SkillTree(unittest.TestCase):
    def test_layout(self):
        self.assertEqual(layout_violations(SCRIPTS), [])

    def test_imports_run_one_way(self):
        self.assertEqual(direction_violations(SCRIPTS), [])

    def test_units_are_reached_through_their_interface(self):
        self.assertEqual(reach_violations(SCRIPTS, skill_files(SCRIPTS), inside_package=True), [])

    def test_tests_reach_units_only_through_their_interface(self):
        self.assertEqual(reach_violations(SCRIPTS, test_files(), inside_package=False), [])

    def test_every_offered_name_exists(self):
        """Each subpackage's __all__ imports cleanly, so an interface cannot name something that is gone."""
        units = [u for u in KINDS if (SCRIPTS / PACKAGE / u).is_dir()]
        code = "import importlib,sys\n" + "".join(
            f"m=importlib.import_module('{PACKAGE}.{u}')\nmissing=[n for n in m.__all__ if not hasattr(m,n)]\nassert not missing, ('{u}', missing)\n" for u in units
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, env={**os.environ, "PYTHONPATH": str(SCRIPTS)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_package_name_does_not_shadow_the_standard_library(self):
        self.assertNotIn(PACKAGE, sys.stdlib_module_names)

    def test_nothing_changes_sys_path(self):
        wrong = []
        for path in skill_files(SCRIPTS) + test_files():
            wrong += [f"{path}:{line}" for line in sys_path_changes(path)]
        self.assertEqual(wrong, [])


class CheckersCatchViolations(unittest.TestCase):
    """The checkers above, pointed at a small tree with one planted violation each."""

    def tree(self, files):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        scripts = root / "scripts"
        base = {
            "cli.py": "from claude.runs import go\n",
            "claude/__init__.py": "",
            "claude/runs/__init__.py": "__all__ = ['go']\nfrom .commands import go\n",
            "claude/runs/commands.py": "from claude.registry import put\ndef go():\n    put()\n",
            "claude/registry/__init__.py": "__all__ = ['put']\nfrom .store import put\n",
            "claude/registry/store.py": "from claude.util import now\ndef put():\n    now()\n",
            "claude/util.py": "def now():\n    return 0\n",
        }
        base.update(files)
        for rel, text in base.items():
            p = scripts / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return scripts

    def test_clean_tree_passes(self):
        s = self.tree({})
        self.assertEqual(direction_violations(s) + reach_violations(s, skill_files(s), inside_package=True), [])

    def test_upward_import_is_caught(self):
        s = self.tree({"claude/util.py": "from claude.registry import put\ndef now():\n    return 0\n"})
        self.assertTrue(direction_violations(s))

    def test_reaching_inside_a_unit_is_caught(self):
        for text in ("from claude.registry.store import put\n", "from claude.registry import hidden\n", "import claude.registry\n", "from claude import registry\n"):
            s = self.tree({"claude/runs/commands.py": text})
            self.assertTrue(reach_violations(s, skill_files(s), inside_package=True), text)

    def test_sideways_feature_import_is_caught(self):
        s = self.tree({"claude/observe/__init__.py": "__all__ = ['look']\nfrom claude.runs import go\nlook = go\n"})
        self.assertTrue(direction_violations(s))

    def test_sys_path_change_is_caught(self):
        s = self.tree({"cli.py": "import sys as s\ns.path.insert(0, 'x')\n"})
        self.assertTrue(sys_path_changes(s / "cli.py"))
        s = self.tree({"cli.py": "import sys\nsys.path[:0] = ['x']\n"})
        self.assertTrue(sys_path_changes(s / "cli.py"))


if __name__ == "__main__":
    unittest.main()
