"""S6: the skill used by a headless orchestrator, draft SKILL.md against a control, on the five scenarios in scenarios.md.

Run from the repository root (real claude, real subscription):
    python3 tests/e2e/run_e2e.py --out .tmp/e2e            # every scenario, both variants
    python3 tests/e2e/run_e2e.py --scenario 3 --variant draft --out .tmp/e2e

Each session gets a fresh project under --out, an orchestrator `claude -p --model sonnet --setting-sources project,local` (so neither the user's live copy of this skill nor their global CLAUDE.md is in it), and a temporary plugin holding only this skill in the variant under test. Workers are started by the skill's CLI and so run with the user's whole environment. Prints one JSON summary line per session and writes the orchestrator's events next to it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL = REPO / ".claude" / "skills" / "claude"
PARENT_IDENTITY = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_SKILL_RUN", "CLAUDE_SKILL_TEST_TIMINGS")

BUGGY = {
    "calc.py": "def add(a, b):\n    return a - b\n",
    "test_calc.py": "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
}

SCENARIOS = {
    1: {
        "name": "delegate",
        "files": {"pkg/__init__.py": "", "pkg/settings/defaults.py": "RETRIES = 3\nREQUEST_TIMEOUT_SECONDS = 42\n", "app.py": "from pkg.settings.defaults import REQUEST_TIMEOUT_SECONDS\n"},
        "prompt": "Use the claude skill to have a Claude worker (model haiku) find where the request timeout default is defined in this project and what its value is. Then tell me the file and the value.",
        "expect": [r"\b42\b", r"defaults\.py"],
    },
    2: {
        "name": "batch",
        "files": {"a.py": "# TODO: rename\nx = 1\n", "b.py": "y = 2\n", "c/d.py": "# TODO: split\nz = 3\n", "pyproject.toml": "[project]\nname = 'demo'\nrequires-python = '>=3.12'\n"},
        "prompt": "Use the claude skill to run three independent read-only Claude workers (model haiku) at the same time: one counts the .py files in this project, one lists the TODO comments with their files, one reports the Python version pyproject.toml requires. Then give me one summary of all three.",
        "expect": [r"\b3\b", r"rename", r"split", r"3\.12"],
    },
    3: {
        "name": "steer",
        "files": {"src/shapes.py": "def area(r):\n    return 3.14 * r * r\n\n\ndef perimeter(r):\n    return 2 * 3.14 * r\n"},
        "prompt": "Use the claude skill to start a Claude worker (model haiku, profile write) that lists every function defined in src/ and writes the list to a file named functions.txt. Right after it has started, change your mind: tell that same running worker to write the list to names.txt instead (do not start a second worker). When it is done, tell me which file it wrote and what is in it.",
        "expect": [r"names\.txt"],
        "files_after": ["names.txt"],
    },
    4: {
        "name": "denied",
        "files": {"README.md": "demo\n"},
        "prompt": "Use the claude skill to have a Claude worker (model haiku, profile write) create the file {outside}/report.txt containing the word done, and also create ./inside.txt containing ok. Then tell me exactly which of the two files were created.",
        "expect": [r"(?i)(denied|not (be )?created|could not|couldn't|blocked|refused|failed)"],
        "absent": ["{outside}/report.txt"],
    },
    5: {
        "name": "read-only-tests",
        "files": BUGGY,
        "prompt": "Find the bug in this project by having a Claude worker (model haiku) run its tests through the claude skill. The worker must not change any file. Tell me which test fails and why.",
        "expect": [r"test_add", r"(?i)subtract|a - b|minus"],
        "read_only": True,
    },
}


def control_text(full):
    """The control SKILL.md: frontmatter, title and the invocation paragraph, nothing else."""
    head, body = full.split("\n---\n", 1)
    lines = body.strip("\n").splitlines()
    title = lines[0]
    para = next(l for l in lines[1:] if l.strip())
    return f"{head}\n---\n\n{title}\n\n{para}\n"


def build_plugin(root, variant):
    plugin = root / f"plugin-{variant}"
    if plugin.exists():
        return plugin
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "claude", "version": "0.0.0-e2e", "description": "e2e copy", "skills": "./skills/"}))
    dest = plugin / "skills" / "claude"
    shutil.copytree(SKILL, dest, ignore=shutil.ignore_patterns("__pycache__"))
    text = (SKILL / "SKILL.md").read_text()
    (dest / "SKILL.md").write_text(text if variant == "draft" else control_text(text))
    return plugin


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_project(path, files):
    path.mkdir(parents=True)
    for rel, text in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "-c", "user.email=e@x", "-c", "user.name=e", "commit", "-q", "-m", "init")


def snapshot(root):
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel.split("/")[0] in (".git", ".claude-runs", ".claude"):
            continue
        out[rel] = p.read_bytes() if p.is_file() and not p.is_symlink() else None
    return out


def skill_calls(events, cli):
    """(command, run_in_background) for every Bash call that ran the skill."""
    calls = []
    for e in events:
        if e.get("type") != "assistant" or e.get("parent_tool_use_id"):
            continue
        for b in e["message"].get("content") or []:
            if b.get("type") == "tool_use" and b.get("name") == "Bash" and "cli.py" in str(b["input"].get("command", "")):
                calls.append((b["input"]["command"], bool(b["input"].get("run_in_background"))))
    return calls


def one_line_ok(command, cli):
    """Whether a call has the shape the pre-approval matches: one line, the entry path written out, no pipe, variable or substitution."""
    if "\n" in command or "\\\n" in command:
        return False
    if not command.startswith(f'uv run "{cli}" '):
        return False
    rest = command[len(f'uv run "{cli}" '):]
    return not re.search(r"(^|[^'\"\w])(\||\$\(|\$[A-Za-z_{]|`)", rest)


def run_session(out, number, variant, timeout):
    sc = SCENARIOS[number]
    root = out / f"{number}-{sc['name']}-{variant}-{int(time.time())}"
    project = root / "project"
    outside = root / "outside"
    outside.mkdir(parents=True)
    make_project(project, sc["files"])
    plugin = build_plugin(out, variant)
    cli = plugin / "skills" / "claude" / "scripts" / "cli.py"
    prompt = sc["prompt"].format(outside=outside)
    before = snapshot(project)
    env = {k: v for k, v in os.environ.items() if k not in PARENT_IDENTITY}
    argv = ["claude", "-p", "--model", "sonnet", "--setting-sources", "project,local", "--plugin-dir", str(plugin), "--output-format", "stream-json", "--verbose",
            "--permission-mode", "default", "--permission-prompts", "none", "--allowedTools", "Skill(claude:claude)", f'Bash(uv run "{cli}" *)', "--", prompt]
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=project, capture_output=True, text=True, env=env, timeout=timeout)
        stdout, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout, code = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
    (root / "orchestrator.jsonl").write_text(stdout)
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    answer = final.get("result") or ""
    calls = skill_calls(events, str(cli))
    commands = [c for c, _ in calls]
    sub = [re.sub(r"^uv run \"[^\"]+\" ", "", c).split()[0] if c.startswith("uv run") else "?" for c in commands]
    waits = [(c, bg) for c, bg in calls if " --wait" in c]
    polls = [c for c in commands if re.search(r" (status|result) ", c) and " --wait" not in c]
    after = snapshot(project)
    summary = {
        "scenario": number,
        "name": sc["name"],
        "variant": variant,
        "exit": code,
        "seconds": round(time.time() - started),
        "cost_usd": final.get("total_cost_usd"),
        "denials": [d.get("tool_name") for d in final.get("permission_denials") or []],
        "skill_loaded": any(e.get("type") == "assistant" and any(b.get("type") == "tool_use" and b.get("name") == "Skill" for b in e["message"].get("content") or []) for e in events),
        "commands": sub,
        "all_one_line": all(one_line_ok(c, str(cli)) for c in commands) if commands else None,
        "waits_in_background": sum(1 for _, bg in waits if bg),
        "waits_in_foreground": sum(1 for _, bg in waits if not bg),
        "polls": len(polls),
        "expect_met": [bool(re.search(p, answer)) for p in sc.get("expect", [])],
        "answer_head": answer[:400],
        "dir": str(root),
    }
    if sc.get("files_after"):
        summary["files_after"] = {f: (project / f).exists() for f in sc["files_after"]}
    if sc.get("absent"):
        summary["absent_ok"] = all(not Path(p.format(outside=outside)).exists() for p in sc["absent"])
    if sc.get("read_only"):
        summary["used_read_only"] = any("--profile read-only" in c for c in commands)
        summary["tree_changed"] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    (root / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return summary


def main():
    ap = argparse.ArgumentParser(description="S6 headless e2e: draft SKILL.md against a control.")
    ap.add_argument("--out", required=True, help="where projects, plugins and events go")
    ap.add_argument("--scenario", default="all", help="1-5 or all")
    ap.add_argument("--variant", choices=("draft", "control", "both"), default="both")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per session")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    numbers = list(SCENARIOS) if args.scenario == "all" else [int(args.scenario)]
    variants = ("draft", "control") if args.variant == "both" else (args.variant,)
    for n in numbers:
        for v in variants:
            print(json.dumps(run_session(out, n, v, args.timeout), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    sys.exit(main())
