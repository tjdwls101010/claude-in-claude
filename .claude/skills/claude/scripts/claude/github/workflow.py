"""The workflow file a schedule is (K2): GitHub Actions YAML written so that GitHub hands every value to the job exactly as given — a prompt as a block scalar with its indentation and final line breaks stated, `${{` escaped so GitHub does not evaluate it — and a `# spec:` comment line holding the same definition as JSON, which is how the skill reads a workflow back (the standard library has no YAML parser)."""

from __future__ import annotations

import json
import math
import re
import shlex

SPEC_PREFIX = "# spec: "
HEADER = "# Written by the claude skill's `schedule` command. Run it again with the same --name to change it; `unschedule` removes it."
# Characters a YAML block scalar cannot carry as they are.
UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f  ﻿]")
SPEC_KEYS = ("name", "cron", "at", "timezone", "profile", "model", "effort", "timeout", "worktree", "runs_on", "project", "cli", "definition", "prompt", "schema")


def workflow_file(name):
    return f"claude-{name}.yml"


def _escape(text):
    """GitHub evaluates `${{ … }}` anywhere in a workflow's values; this writes a literal `${{` (probe 11)."""
    return text.replace("${{", "${{ '${{' }}")


def unsafe_text(text):
    """The first character of `text` a workflow cannot carry exactly (control characters other than tab and newline), or None."""
    m = UNSAFE.search(text or "")
    return m.group(0) if m else None


def _block(text, indent):
    """`text` as a YAML block scalar whose lines sit at `indent` spaces: the indentation indicator keeps leading spaces of the first line, the chomping indicator keeps the final line breaks exactly."""
    body = text.replace("\r\n", "\n")
    if body.endswith("\n\n"):
        chomp = "+"
    elif body.endswith("\n"):
        chomp = ""
    else:
        chomp = "-"
    lines = _escape(body).split("\n")
    if body.endswith("\n"):
        lines = lines[:-1]
    out = ["|2" + chomp]
    out += [(" " * indent + line) if line else "" for line in lines]
    return "\n".join(out)


def _q(text):
    """A shell word for the step's `run:` line."""
    return shlex.quote(str(text))


def _string(text):
    """A YAML double-quoted string (JSON's syntax is a subset of it), `${{` escaped: no path, label or model can end a value early (` #`), open a mapping (`: `) or change type (`true`, `123`)."""
    return _escape(json.dumps(text, ensure_ascii=False))


def _step_args(step, spec):
    args = ["__scheduled", step, "--name", spec["name"], "--project", spec["project"], "--profile", spec["profile"], "--model", spec["model"], "--effort", spec["effort"], "--timeout", str(int(spec["timeout"]))]
    args += ["--at", spec["at"]] if spec.get("at") else ["--cron", spec["cron"]]
    args += ["--timezone", spec["timezone"]]
    if spec.get("worktree"):
        args.append("--worktree")
    args += ["--workflow", workflow_file(spec["name"]), "--definition", spec["definition"]]
    return _string(f'uv run {_q(spec["cli"])} ' + " ".join(_q(a) for a in args))


def _env(spec, indent, token):
    pad = " " * indent
    lines = [f"{pad}CLAUDE_SCHEDULE_MODE: ${{{{ inputs.mode }}}}", f"{pad}CLAUDE_SCHEDULE_SOURCE: ${{{{ inputs.source }}}}", f"{pad}CLAUDE_SCHEDULE_PROMPT: {_block(spec['prompt'], indent + 2)}"]
    if spec.get("schema"):
        lines.append(f"{pad}CLAUDE_SCHEDULE_SCHEMA: {_block(spec['schema'], indent + 2)}")
    if token:
        lines.append(f"{pad}GH_TOKEN: ${{{{ github.token }}}}")
    return "\n".join(lines)


def render_workflow(spec):
    """The workflow text for `spec` (see SPEC_KEYS): a cron or a one-off `at` in `timezone`, a manual `mode` (run or check) and the dispatcher's `source` input, `concurrency` that queues every trigger in order (K5), a job on the runners `runs_on` names, limited to the run's timeout plus 10 minutes, with a Run step and an always-run Finish step that take the same flags and environment (K19). Only a one-off asks for `actions: write`, which its Finish step needs to disable the workflow (K7, K8)."""
    name = spec["name"]
    if spec.get("at"):
        when = spec["at"]
        minute, hour, day, month = when[14:16], when[11:13], when[8:10], when[5:7]
        cron = f"{int(minute)} {int(hour)} {int(day)} {int(month)} *"
    else:
        cron = spec["cron"]
    record = {k: spec.get(k) for k in SPEC_KEYS}
    permissions = "permissions:\n  actions: write" if spec.get("at") else "permissions: {}"
    runs_on = ", ".join(_string(label) for label in spec["runs_on"])
    minutes = math.ceil(int(spec["timeout"]) / 60) + 10
    return "\n".join([
        HEADER,
        SPEC_PREFIX + json.dumps(record, ensure_ascii=False, sort_keys=True).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"),
        f"name: claude · {name}",
        f"run-name: {name} · ${{{{ inputs.mode == 'check' && 'check' || inputs.source || github.event_name }}}}",
        "on:",
        "  schedule:",
        f"    - cron: '{cron}'",
        f"      timezone: {spec['timezone']}",
        "  workflow_dispatch:",
        "    inputs:",
        "      mode:",
        "        description: run starts the worker; check only verifies that this runner can log in and start one",
        "        type: choice",
        "        options: [run, check]",
        "        default: run",
        "      source:",
        "        description: Leave empty for a manual run. The local dispatcher sets it so that a late duplicate is skipped.",
        "        type: string",
        "        required: false",
        permissions,
        "concurrency:",
        f"  group: claude-{name}",
        "  cancel-in-progress: false",
        "  queue: max",
        "jobs:",
        "  run:",
        f"    runs-on: [{runs_on}]",
        f"    timeout-minutes: {minutes}",
        "    steps:",
        "      - name: Run",
        "        env:",
        _env(spec, 10, token=False),
        f"        run: {_step_args('run', spec)}",
        "      - name: Finish",
        "        if: always()",
        "        env:",
        _env(spec, 10, token=True),
        f"        run: {_step_args('finish', spec)}",
        "",
    ])


def parse_spec(text):
    """The definition a workflow's `# spec:` line holds, or None when the workflow is not one this skill wrote: its first line is not the skill's header, or it has no spec line, or the spec names no schedule. ValueError when the line is there but is not a JSON object."""
    if not (text or "").startswith(HEADER + "\n"):
        return None
    for line in (text or "").splitlines():
        if line.startswith(SPEC_PREFIX):
            obj = json.loads(line[len(SPEC_PREFIX):])
            if not isinstance(obj, dict):
                raise ValueError("the spec line does not hold a JSON object")
            return obj if obj.get("name") else None
    return None
