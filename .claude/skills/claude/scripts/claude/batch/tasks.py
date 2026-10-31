"""A batch's tasks: each --task is a prompt, each --tasks-file line a JSON object of the fields below, checked before anything starts."""

from __future__ import annotations

import json
from pathlib import Path

from claude.claude_cli import PROFILES
from claude.errors import Refusal
from claude.runs import EFFORTS

# field → allowed values, or None for any non-empty string
TASK_FIELDS = {"prompt": None, "kind": ("start", "resume"), "resume": None, "label": None, "profile": PROFILES, "model": None, "effort": EFFORTS, "schema": None, "cwd": None}


def bad(message):
    return Refusal(message, arguments=True, help="batch --help")


def check_task(task, where):
    if not isinstance(task, dict):
        raise bad(f"{where}: a task is a JSON object")
    unknown = sorted(set(task) - set(TASK_FIELDS))
    if unknown:
        raise bad(f"{where}: unknown field(s) {', '.join(unknown)}; a task takes {', '.join(TASK_FIELDS)}")
    for key, value in task.items():
        allowed = TASK_FIELDS[key]
        if not isinstance(value, str) or not value.strip():
            raise bad(f"{where}: {key} must be a non-empty string")
        if allowed and value not in allowed:
            raise bad(f"{where}: {key} must be one of {', '.join(allowed)}")
    if "prompt" not in task:
        raise bad(f"{where}: no prompt")
    kind = task.get("kind", "start")
    if kind == "resume" and "resume" not in task:
        raise bad(f"{where}: kind resume needs a resume field naming the run or session")
    if kind != "resume" and "resume" in task:
        raise bad(f"{where}: a resume field needs kind resume")
    if "cwd" in task and not Path(task["cwd"]).expanduser().is_dir():
        raise bad(f"{where}: cwd {task['cwd']} is not a directory")
    if "schema" in task and not Path(task["schema"]).expanduser().is_file():
        raise bad(f"{where}: schema {task['schema']} is not a file")
    return {**task, "kind": kind}


def parse_tasks(task_args, tasks_file):
    """The batch's tasks in order: every --task, then every line of the tasks file."""
    tasks = [check_task({"prompt": t}, f"--task {i}") for i, t in enumerate(task_args or [], 1)]
    if tasks_file:
        try:
            lines = Path(tasks_file).expanduser().read_text(encoding="utf-8").splitlines()
        except OSError as e:
            raise bad(f"--tasks-file {tasks_file}: {e.strerror or e}")
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as e:
                raise bad(f"--tasks-file line {n}: not JSON ({e})")
            tasks.append(check_task(obj, f"--tasks-file line {n}"))
    if not tasks:
        raise bad("no task: give --task or --tasks-file")
    return tasks
