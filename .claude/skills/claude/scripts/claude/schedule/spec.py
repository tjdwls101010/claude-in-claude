"""A schedule's definition: checking a name, merging what the command line gives over what the committed workflow records over the skill's defaults (K2, as `resume` inherits a session's settings), and the refusals that cost nothing."""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from claude.errors import Refusal
from claude.github import name_problem, unsafe_text
from claude.launchd import agent_identity, calendar_entries
from claude.runs import DEFAULTS
from claude.util import nfc

from .times import CronError, fire_times, parse_cron

# A name's length in UTF-16 units, the unit this Mac's file names are counted in. The dispatcher's plist is claude-schedule.<owner>-<repository>.<name>.plist; with GitHub's longest owner (39) and repository (100) that is 163 units around the name, so 80 fits a file name (255) for any repository, with room to spare.
NAME_UNITS = 80
# What a name was before files took it as given. A schedule of such a name may live in the file names had then (claude-<name>.yml).
OLD_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")
# A group name's length, which a worktree group must fit together with the run id and attempt (K10).
GROUP_CHARS = 40
UNSEEN = {"Cc": "a control character", "Zl": "a line separator", "Zp": "a paragraph separator", "Zs": "a space other than the ordinary one", "Cf": "a formatting character that does not show", "Cs": "half of a surrogate pair", "Co": "a private-use character"}
LABEL_RULE = re.compile(r"^[A-Za-z0-9._-]+$")
SCHEDULE_DEFAULTS = {"model": DEFAULTS["model"], "effort": DEFAULTS["effort"], "timeout": 3600, "worktree": False, "runs_on": ["self-hosted"]}
AT_FORMAT = "%Y-%m-%dT%H:%M"
AT_RULE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def bad(message):
    return Refusal(message, arguments=True, help="schedule --help")


def dispatcher_label(repo, name):
    """The LaunchAgent label of schedule `name` of `owner/repo`."""
    owner, rname = repo.split("/", 1)
    return f"claude-schedule.{owner}-{rname}.{name}"


def dispatcher_holder(repo, name):
    """Who else holds the path of this schedule's dispatcher plist on this Mac, as `{label, repo, plist}` (see `holder_words`), or None when the path is free or holds this schedule's own — a plist whose `Label` is this label to the letter and whose command dispatches to this repository. A label joins owner, repository and name without marking where each ends, and the file system ignores letter case and Unicode form, so another schedule's plist can sit there; one that cannot be read (`label` None), or names no repository (`repo` None), is not known to be this schedule's."""
    label = dispatcher_label(repo, name)
    found = agent_identity(label)
    if found is None:
        return None
    argv = found["argv"]
    target = argv[argv.index("--repo") + 1] if "--repo" in argv[:-1] else None
    if found["label"] == label and target == repo:
        return None
    return {"label": found["label"], "repo": target, "plist": found["plist"]}


def holder_words(held, code=str):
    """Whoever `dispatcher_holder` found, in words. `code` writes the label, repository and path — as they are for a JSON reply, as inline code for markdown."""
    if held["label"] is None:
        return f"a plist that cannot be read ({code(held['plist'])})"
    return f"the dispatcher {code(held['label'])}" + (f" of {code(held['repo'])}" if held["repo"] else ", which names no repository") + f" ({code(held['plist'])})"


def _noncharacter(ch):
    """Whether `ch` is one of the 66 code points Unicode keeps unassigned for good."""
    n = ord(ch)
    return 0xFDD0 <= n <= 0xFDEF or n & 0xFFFE == 0xFFFE


def _unseen(name):
    """Why `name` would not show everything it holds, or None. The zero-width joiner and non-joiner stay: emoji sequences and several scripts are written with them. A code point the Unicode tables leave unassigned stays too, unless it is a noncharacter: it may be a character newer than the tables of the Python that runs this — an emoji of Unicode 16 is unassigned to Python 3.13 — and a name must get the same answer whichever Python `uv run` picks, or `unschedule` could refuse a schedule another Python made."""
    for ch in name:
        if _noncharacter(ch):
            return f"U+{ord(ch):04X} is a noncharacter, which Unicode never assigns, and a name must show everything it holds or two names could look the same"
        kind = unicodedata.category(ch)
        if kind in ("Cc", "Zl", "Zp", "Cs", "Co") or (kind == "Zs" and ch != " ") or (kind == "Cf" and ch not in "\u200c\u200d"):
            return f"U+{ord(ch):04X} is {UNSEEN[kind]}, and a name must show everything it holds or two names could look the same"
    if name.startswith(" "):
        return "it starts with a space, which does not show"
    return None


def check_name(name):
    """`name` in NFC, the one form every use of it takes from here on (GitHub keeps the NFC and NFD spellings of a file as two paths) — or the Refusal that says why it cannot be a schedule's name. A name is used as given for the workflow file, the title in Actions, this Mac's dispatcher label and state directory, so each reason is what one of them cannot take; anything else is the person's to choose."""
    name = nfc(name or "")
    if not name:
        raise bad("--name is empty")
    problem = _unseen(name) or name_problem(name)
    units = len(name.encode("utf-16-le", "surrogatepass")) // 2
    if not problem and units > NAME_UNITS:
        problem = f"it is {units} UTF-16 units long (an emoji counts as two) and a name holds {NAME_UNITS}: this Mac's dispatcher file is named after the repository and the schedule together, and must stay a file name"
    if problem:
        raise bad(f"--name {name!r}: {problem}")
    return name


def was_old_name(name):
    """Whether `name` could have been a schedule's while files were claude-<name>.yml."""
    return bool(OLD_NAME.fullmatch(name))


def worktree_group(name, run_id, attempt):
    """The group one job's `--worktree` run takes: an ASCII slug of the schedule's name, then the job's run id and attempt, within a group name's length — a group name is also a git branch and a Claude Code worktree name, which do not take what a schedule's name may hold. The run id makes it unique, so names with one slug do not collide; a name with no ASCII letter or digit is `schedule`."""
    tail = f"-{run_id}-{attempt}"
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[: max(0, GROUP_CHARS - len(tail))].rstrip("-")
    return (slug or "schedule") + tail


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
            if not AT_RULE.match(spec["at"]):
                raise ValueError
            when = datetime.strptime(spec["at"], AT_FORMAT).replace(tzinfo=ZoneInfo(timezone))
        except ValueError:
            raise bad(f"--at {spec['at']!r}: give a local time as YYYY-MM-DDTHH:MM, zero-padded")
        if when.timestamp() <= now:
            if flags.get("at"):
                raise bad(f"--at {spec['at']} is not in the future ({timezone})")
            raise bad(f"this one-off's time {spec['at']} has passed; give a new --at to run it again")
    else:
        try:
            parse_cron(spec["cron"])
        except CronError as e:
            raise bad(f"--cron: {e}")
        if not fire_times({"cron": spec["cron"], "at": None, "timezone": timezone}, now, 1):
            raise bad(f"--cron {spec['cron']!r} never fires")
    try:
        calendar_entries(fields_of(spec))
    except ValueError as e:
        raise bad(str(e))
    spec.update({"name": flags["name"], "timezone": timezone, "project": project, "cli": cli, "timeout": int(spec["timeout"])})
    spec["definition"] = (recorded or {}).get("definition") if keep_definition and recorded else secrets.token_hex(4)
    return spec
