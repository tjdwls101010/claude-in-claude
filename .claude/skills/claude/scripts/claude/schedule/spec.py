"""A schedule's definition: checking a name, merging what the command line gives over what the committed workflow records over the skill's defaults (K2, as `resume` inherits a session's settings), and the refusals that cost nothing."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from claude.errors import Refusal
from claude.github import unsafe_text
from claude.launchd import calendar_entries
from claude.runs import DEFAULTS

from .times import CronError, parse_cron

# The worktree group <name>-<run id>-<attempt> must fit a group name's 40 characters with an 11-digit run id and a spare digit (K10).
NAME_RULE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
LABEL_RULE = re.compile(r"^[A-Za-z0-9._-]+$")
SCHEDULE_DEFAULTS = {"model": DEFAULTS["model"], "effort": DEFAULTS["effort"], "timeout": 3600, "worktree": False, "runs_on": ["self-hosted"]}
AT_FORMAT = "%Y-%m-%dT%H:%M"


def bad(message):
    return Refusal(message, arguments=True, help="schedule --help")


def dispatcher_label(repo, name):
    """The LaunchAgent label of schedule `name` of `owner/repo`."""
    owner, rname = repo.split("/", 1)
    return f"claude-schedule.{owner}-{rname}.{name}"


def check_name(name):
    if not NAME_RULE.match(name or ""):
        raise bad(f"--name {name!r}: lowercase letters, digits and hyphens, starting with a letter or digit, at most 24")


def fields_of(spec):
    """The cron fields a spec fires on — a one-off's `at` as the dated cron its workflow carries."""
    if spec.get("at"):
        d = datetime.strptime(spec["at"], AT_FORMAT)
        return {"minute": [d.minute], "hour": [d.hour], "day": [d.day], "month": [d.month], "weekday": None}
    return parse_cron(spec["cron"])


def merge(flags, recorded, *, timezone, project, cli, now, keep_definition=False):
    """The spec to commit. `flags` holds what the command line gave (None for absent): name, prompt, schema (its text), cron, at, profile, model, effort, timeout, worktree (True, False or None), runs_on. `recorded` is the committed workflow's spec, or None for a new schedule, which then needs a prompt, a profile and a time. The time zone, project and skill path always come from now, so calling `schedule --name X` again refreshes paths that moved (K3). A fresh `definition` is drawn unless `keep_definition` (K8)."""
    base = {**SCHEDULE_DEFAULTS, "prompt": None, "schema": None, "cron": None, "at": None, "profile": None}
    if recorded:
        base.update({k: v for k, v in recorded.items() if k in ("prompt", "schema", "cron", "at", "profile", "model", "effort", "timeout", "worktree", "runs_on")})
    spec = dict(base)
    for key in ("prompt", "schema", "profile", "model", "effort", "timeout", "runs_on"):
        if flags.get(key) is not None:
            spec[key] = flags[key]
    if flags.get("worktree") is not None:
        spec["worktree"] = flags["worktree"]
    if flags.get("cron"):
        spec.update({"cron": flags["cron"], "at": None})
    if flags.get("at"):
        spec.update({"at": flags["at"], "cron": None})
    missing = [what for what, ok in (("a prompt (PROMPT or --prompt-file)", spec["prompt"]), ("--profile", spec["profile"]), ("--cron or --at", spec["cron"] or spec["at"])) if not ok]
    if missing:
        raise bad(f"a new schedule needs {', '.join(missing)}")
    if not str(spec["prompt"]).strip():
        raise bad("the prompt is empty")
    for what in ("prompt", "schema"):
        ch = unsafe_text(spec.get(what))
        if ch:
            raise bad(f"the {what} holds the control character {ch!r}, which a workflow file cannot carry exactly")
    if spec["worktree"] and spec["profile"] == "read-only":
        raise bad("--worktree isolates a worker that writes; a read-only worker gets no worktree")
    for label in spec["runs_on"]:
        if not LABEL_RULE.match(label):
            raise bad(f"--runs-on {label!r} is not a runner label")
    if "self-hosted" not in spec["runs_on"]:
        spec["runs_on"] = ["self-hosted", *spec["runs_on"]]
    if spec["at"]:
        try:
            when = datetime.strptime(spec["at"], AT_FORMAT).replace(tzinfo=ZoneInfo(timezone))
        except ValueError:
            raise bad(f"--at {spec['at']!r}: give a local time as YYYY-MM-DDTHH:MM")
        if flags.get("at") and when.timestamp() <= now:
            raise bad(f"--at {spec['at']} is not in the future ({timezone})")
    else:
        try:
            parse_cron(spec["cron"])
        except CronError as e:
            raise bad(f"--cron: {e}")
    try:
        calendar_entries(fields_of(spec))
    except ValueError as e:
        raise bad(str(e))
    spec.update({"name": flags["name"], "timezone": timezone, "project": project, "cli": cli, "timeout": int(spec["timeout"])})
    spec["definition"] = (recorded or {}).get("definition") if keep_definition and recorded else secrets.token_hex(4)
    return spec
