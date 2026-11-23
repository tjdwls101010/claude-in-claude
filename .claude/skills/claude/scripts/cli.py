# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Drive Claude Code workers (`claude -p`) as managed subagents. This file is the whole command surface — every flag and help text, each command's `Prints:` and `Exits:`, the checks made from the arguments alone, dispatch into the `claude` package, and rendering — and the entry point a detached supervisor re-executes. What a command does lives in `claude/`.

Exit codes:
    0  success
    1  the registry's state refused the command, or what it asked for failed; the reply carries `error`
    2  the command line itself must change; the reply carries `error` and the `help` to read
    3  `doctor` found a blocker
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from claude.batch import TASK_FIELDS, batch, clean
from claude.claude_cli import PROFILES, VERSION_FLOOR_TEXT
from claude.doctor import doctor
from claude.errors import Refusal
from claude.observe import GROUP_MESSAGE_CAP, LISTING_ROWS, STALL_SECONDS, log, result, status
from claude.runs import DEFAULTS, EFFORTS, SEND_LIMIT, resume, send, start, stop, supervise
from claude.schedule import SCHEDULE_DEFAULTS, schedule, scheduled_finish, scheduled_run, schedules, unschedule

EXIT_REFUSED, EXIT_ARGUMENTS, EXIT_BLOCKED = 1, 2, 3

ROOT_DESC = "Start Claude Code workers in the background and manage them like subagents: a handle at once, progress, steering, stopping, continuing, and the result — text or schema-shaped JSON — when it is ready."

ROOT_EPILOG = """\
Every command prints one JSON line on stdout — its result, or a refusal carrying `error` — unless its --help says it prints text.
Exit codes: 0 success; 1 the registry's state refused the command, or what it asked for failed, and `error` says why; 2 the command line must change, and the reply's `help` names the --help to read; 3 `doctor` found a blocker.
Runs live in .claude-runs/ of the repository's main checkout (outside git, of the current directory); --project or --runs-dir point a command at another registry."""

PROFILE_HELP = f"""what the worker may do (default {DEFAULTS['profile']}). The profile is a restriction laid over your own Claude Code settings, not a replacement: settings that widen it are listed in the reply's `profile_exceptions`.
  read-only  reads anything, and runs any shell command inside a sandbox that can write only its TMPDIR and ~/.cache and reach only hosts your settings allow (none by default) — so it can run tests and builds and bring back what they printed. The sandbox, not a permission check, is the boundary. No edit tools. Hooks, MCP tools and WebFetch run outside the sandbox under your permission rules.
  write      edits and shell writes inside the working directory, any shell command inside the same sandbox and network as read-only; edits outside it are denied and listed in `permission_denials`.
  auto       Claude Code's auto-mode classifier reviews each call: network and writes outside the directory are possible, and a call it blocks is a denial. A model without auto mode starts in another mode and the reply says `mode_mismatch`."""

RUN_EPILOG = f"""\
Answers once claude reports its first init (up to 15 s), so a start that fails at once — not logged in, a bad flag, a claude older than {VERSION_FLOOR_TEXT} — says so here. A detached supervisor drives the run, so it outlives this command and nothing announces its end: run the reply's `next.command` in the background; it returns when the run ends or needs attention, and prints the result.
The worker inherits your whole Claude Code environment — CLAUDE.md files, skills, hooks, plugins, MCP servers, memory — under the profile's restrictions, with background tasks off so its turn ending is the run ending. It is told nobody can answer it, that its final message is what you receive, to leave git commits, branches, pushes and merges to you unless the prompt asks, and that it cannot start workers.
Model and effort default to {DEFAULTS['model']} and {DEFAULTS['effort']} whatever your settings say."""

START_DESC = f"""\
Start a fresh worker session on PROMPT, detached.
Prints: one JSON line — `run_id`, `session_id`, `state`, `next` (the `result --run <id> --wait` call to run in the background), `profile`, `permission_mode` (what claude reported), `mode_mismatch`, `model`, `effort`, `cwd`, `concurrent_writers` (other live runs that can write in the same directory), `profile_exceptions`, `events` (the raw stream-json file); `error` and `stderr_tail` instead of `next` when the run failed while starting.
Exits: 0 started; 1 refused or failed — run from inside a worker, claude missing or older than {VERSION_FLOOR_TEXT}, or the run failed before its first init (`error` says why); 2 the command line must change — no prompt or an empty one, an unreadable --prompt-file or --schema, a --cwd that is not a directory, or anything else the parser refuses."""

RESUME_DESC = f"""\
Run another turn on an existing session, detached: a new run with its own events, under the profile, model, effort and schema the session's last run recorded, except where a flag changes them — every turn re-sends them, because a resumed `claude -p` restores only the model. Continue a session when the new work builds on what it worked out; start fresh when it does not.
Prints: one JSON line as `start` prints, plus `profile_changed_from` when --profile changed it, and `note` for a session the registry never saw.
Exits: 0 started; 1 refused or failed — the session has a live run (`instead` says what to do: `send` while it reads messages, otherwise `stop` first), run from inside a worker, claude missing or older than {VERSION_FLOOR_TEXT}, an unknown REF that is not a session id, or the run failed before its first init (a session claude does not know fails here); 2 the command line must change — no REF, no prompt or an empty one, a session the registry never saw without --profile, or anything else the parser refuses."""

SEND_DESC = f"""\
Write a message into a live run while it works, to correct or extend what it is doing. By default the message has priority `next`: Claude Code reads it once the tools it is running finish, in the same turn or, if the turn ends first, as the next one. --interrupt sends it with priority `now`, which ends the running turn and starts on the message. The run ends once every message has been answered.
Prints: one JSON line — `run_id`, `message_uuid`, `priority`, `delivered` (whether the supervisor wrote it to the worker within 10 s), and `note` when it did not.
Exits: 0 queued; 1 refused — the run no longer reads messages (it ended, is finishing, or its supervisor is gone; `instead` says what to do), it already took {SEND_LIMIT} messages, no such run, or run from inside a worker; 2 the command line must change — no REF, no message or an empty one."""

BATCH_DESC = f"""\
Start several runs as one named group: each --task, then each --tasks-file line, is a member started as `start` (or `resume`) would start it, with the group's flags as its defaults. The group is one name for `status`, `result` and `stop` with --group, and for `clean`; it outlives the session that started it, and its name stays reserved until `clean` releases it. N workers spend the same subscription limits N times over.
Prints: one JSON line — `group`, `spawned`, `requested`, `next` (the `result --group <name> --wait` call to run in the background, absent when nothing started), `runs` (per member its `index`, `label`, `run_id`, `state`, `cwd`, `worktree`, `profile`, or the `error` that kept it from starting), and `worktrees` when members got checkouts or `shared_tree` when several writers share one directory.
Exits: 0 every member's start was tried, even when some failed (they carry `error`); 1 refused before anything started — the name is reserved, a worktree of that name is left from an earlier group, run from inside a worker; 2 the command line must change — a --group that breaks the naming rule, no task, a tasks file that cannot be read or a line that is not a valid task (an unknown field, a value outside its set, kind `resume` without `resume`), or anything else the parser refuses."""

BATCH_EPILOG = f"""\
Tasks file: one JSON object per line with the fields {', '.join(TASK_FIELDS)}. `kind` is `start` (default) or `resume`; a resume line names the run or session in `resume` — a next round is a batch of resume lines, one per member, after every member has ended.
--worktree: a member gets its own git worktree (Claude Code's `--worktree <group>-<index>`, at .claude/worktrees/<group>-<index> on branch worktree-<group>-<index>) when it is a fresh start, its profile is write or auto, it has no cwd of its own, and the repository has a commit. The worktree starts from your local HEAD: none of your uncommitted changes, nothing git ignores except what .worktreeinclude copies. Moving changes back into your tree is yours to do; `clean` removes the worktrees afterwards. A resumed member stays in the directory its session ran in.
Each member is told its group's name and size, and a worktree member where its checkout is, which commit it came from and how many uncommitted files your tree has."""

CLEAN_DESC = """\
Remove a group's worktrees and release its name once nothing of it is left. A worktree is removed only when that loses nothing: no change to a tracked file, and every untracked or ignored entry a .worktreeinclude copy or a file startup created that is unchanged since. A member's branch is deleted when it has no commits beyond the base, and never otherwise. Live work is never removed, --force or not.
Prints: one JSON line — `group`, `removed` (per worktree its `path`, `branch`, and `branch_deleted` or `branch_kept`), `kept` (per worktree the `reason`, the paths that would be lost, `occupied_by` with the `stop` call when another live run works there), `name_released`, `forced`, and `note` when the name stays reserved.
Exits: 0 cleaned as far as it could (`name_released` says whether all of it); 1 refused — no such group, a live member (`instead` stops the group), or run from inside a worker; 2 the command line must change — no --group."""

STATUS_DESC = f"""\
What the registry knows: every live run plus the {LISTING_ROWS} newest, one run in full, or one group.
Prints: one JSON line. With no selector: `registry`, `live` (run ids), `runs` (a short row each: `run_id`, `session_id`, `state`, `label`, `group`, `profile`, `model`, `idle_seconds`, `error`, `attention`, `last_message`), `runs_truncated`, `groups` (each with its `group_state`), and the newest `rate_limit` any run observed. With --group: `group`, `group_state`, `running`, `done`, `failed`, `unstarted`, and each member's full row. With --run: that run's full row — the above plus `stored_state`, `permission_mode`, `mode_mismatch`, `cwd`, `created`, `ended`, `elapsed_seconds`, `exit_code`, `in_progress` (calls without a result yet), `tasks_open`, `permission_denials`, `files_edited`, `tool_calls`, `messages`, `unanswered`, `undelivered`, `stdin_open`, `retrying_since`, `rate_limit`, `cost_usd`, `usage`, `profile_exceptions`, `stderr_tail` for a failure, `still_writing` when claude outlived its supervisor, `events`.
Exits: 0 answered; 1 refused — no such run or group, an ambiguous prefix, or a meta.json or manifest that does not parse; 2 the command line must change — --run with --group."""

STATUS_EPILOG = f"""\
States:
  starting     published; claude has not reported its init
  running      claude has the turn
  retrying     running, and the last event is an API retry (`retrying_since` says since when)
  stalled      starting, running or finishing with no event for {STALL_SECONDS} s; advisory, nothing is killed — read `in_progress` beside it
  finishing    the answer is in and stdin is closed, but claude is still running something
  completed    ended: the last answer succeeded
  failed       ended: claude exited non-zero, the answer is an error, or a hook ended the only message (`error` says which)
  interrupted  ended: stopped
  timed_out    ended: its --timeout passed
  orphaned     ended: its supervisor died without recording an outcome; `still_writing` says claude is still running
`attention` lists what needs a look now: `stalled`, `retrying` for 120 s, `rate_limited` (a rejected rate limit), `finishing` for 120 s, `possibly_blocked`.
A group's `group_state` is `running` while any member is live, `completed` when every member completed, and `partial` otherwise — a failure, a stop, a timeout or a member that never started."""

LOG_DESC = """\
What one run did, read from its events.
Prints: text, one line per event — `init model=… mode=… cwd=…` (again when either changes), `msg <text>` with the whole message, `bash exit=<n> out=<bytes>B <command>` with the head and tail of the output indented beneath a failure, `edit|write|read <path>`, `grep|glob <pattern>`, `fetch <url>`, `search <query>`, `skill <name>`, `agent <type> <description> tools=<n> out=<bytes>B`, `mcp <server>/<tool> ok|error`, `denied <tool> <input>`, `sent <priority> <message>`, `task <status> <description>`, `retry attempt=<a>/<max> error=<kind> status=<http>`, `ratelimit <status> 5h=<%> 7d=<%>` when the status changes, `compact`, `result <subtype> turns=<n> terminal=<reason> cost=$<x>` (with `origin=task-notification` for a background follow-up), `running <tool> <summary>` for calls still without a result — then `run=<id> state=<state>`.
Exits: 0 printed; 1 refused — no such run; 2 the command line must change — no --run."""

RESULT_DESC = f"""\
What a run or a group concluded: at once (partial while live), or with --wait once it ends or needs attention.
Prints: a JSON header line — `run_id`, `session_id`, `state`, `exit_code`, `error`, `attention`, `answered` (the messages the answer replies to), `unanswered`, `last_message_unanswered`, `answer_unconfirmed` (claude did not say which message it answered), `blocked_by_hook`, `last_message_blocked`, `possibly_blocked`, `permission_denials`, `files_edited`, `files_edited_note`, `tool_calls`, `usage`, `cost_usd`, `followups` (background follow-up turns, not the answer), `mode_mismatch`, `profile_exceptions`, `message_bytes`, and `note` and `next` while the run is live — then the final message. A --schema run prints one indented JSON document instead, whose `json` is the structured output (null while starting or running). Once a run is `finishing` its answer is decided: the text and `json` are the answer, and `note` says claude is still running something. For a group: a JSON header — `group`, `group_state`, `overlaps` (paths more than one member edited, with their indexes), `totals`, `attention` (members that need a look), `members` (each one's `state`, `bytes`, `shown_bytes`, counts) and `next` while live — then per member a `--- [<index>:<label>] run=<id> state=<state> bytes=<n>` line and its message cut to {GROUP_MESSAGE_CAP} B.
Exits: 0 printed, whatever the state, also when --wait-timeout passes; 1 refused — no such run or group, or a --schema run that ended without structured output (`message` carries its text); 2 the command line must change — neither or both of --run and --group, --wait-timeout without --wait or not positive."""

RESULT_EPILOG = f"""\
--wait on a group returns when every member has ended or any member has new attention. --wait returns early when attention appears that was not there when it began: no event for {STALL_SECONDS} s (`stalled`), API retries for 120 s (`retrying`), a rejected rate limit (`rate_limited`), claude still running 120 s after the answer (`finishing`), or a turn that ended with no reply and no hook notice (`possibly_blocked`). The header's `attention` says which, with what the run was doing; its `next` waits again for something new. Nothing is stopped for it.
`files_edited` lists edit-tool calls; files a shell command wrote are not in it."""

STOP_DESC = """\
Stop runs through their recorded process groups, never by name: SIGINT, then SIGTERM after 10 s, then SIGKILL 3 s later. SIGINT first lets Claude Code end the turn so the session can be resumed.
With --group, every member's newest run.
Prints: one JSON line — `stopped`, an entry per run with `run_id`, `session_id`, `signals_sent` and `state` (`interrupted` for a run that was live; one that had ended keeps its state, with `note`).
Exits: 0 every run was tried; 1 refused — run from inside a worker, or no such run or group; 2 the command line must change — neither or both of --run and --group."""


DOCTOR_DESC = f"""\
The environment a run would start in, checked without starting a worker: Python; claude on PATH and its version against {VERSION_FLOOR_TEXT}; login (`authMethod`, `subscriptionType`); what the read-only and write sandbox needs on this platform; the account's usage limits now, from `claude -p /usage` in safe mode (no model call); the registry, its live runs, groups and worktrees under .claude/worktrees; and settings in your files that widen the read-only and write profiles.
Prints: one JSON line — `ok`, `blockers`, `warnings`, then `python`, `claude` (`path`, `version`, `floor`, `verified`), `auth`, `sandbox` (`platform`, `supported`, `missing`), `quota` (`limits`, each with `kind`, `percent`, `resets_at`, `scope`, `severity`; or `error`), `skill_dir`, `entry`, `invocation` (the command form the pre-approval matches), `registry` (`path`, `exists`, `writable`, `live_runs`, `groups`, `worktrees`), `profile_exceptions` per profile, and `schedule`: what scheduling would need from here — `platform_ok`, `gh` (`path`, `logged_in`, `workflow_scope`), `repo` (`name`, `private`, `default_branch`, or `error`), `runners` (`registered`, this Mac's services in `local`, and `problems` as `schedule` reports them). This doctor runs in your login session and cannot see what a runner's service sees; a check run (`schedule`'s `next`) proves that. What scheduling lacks is a warning, never a blocker.
Exits: 0 no blocker; 3 a blocker would stop every run — no claude, a claude older than {VERSION_FLOOR_TEXT}, not logged in, Python below 3.11, a registry that cannot be written; 2 an argument the parser refuses."""

SCHEDULE_DESC = f"""\
Run a worker later, once or on a schedule, unattended on this Mac, with GitHub Actions as its record and controls. Commits .github/workflows/NAME.yml to the repository's default branch through the GitHub API (no pull request; it holds the prompt, which stays in git history after `unschedule`) and installs a LaunchAgent on this Mac that starts the workflow on time; GitHub's own cron in the file is a late backup, and a late duplicate of a time that already ran is skipped. Each run is a job on this repository's self-hosted runner: the worker starts as `start` would, nobody can answer it, the job holds it until it ends (--timeout is its limit; attention is only a warning), and the job's summary shows the prompt, the answer, the changes, the activity and how to continue it here. A read-only run that failed, timed out or lost its supervisor (not one that completed or was stopped) is tried once more by the next automatic trigger for the same time.
Called again with the same --name, only the flags given change; everything else keeps what the committed workflow records, and the workflow is enabled again if it was disabled.
Prints: one JSON line — `name`, `repo`, `workflow` (`status` committed or unchanged, `path`, `url`, `commit`, `was_disabled`), `dispatcher` (`status` installed or failed, `label`, `plist`, `error`), `fires` (`timezone`, `cron` or `at`, the `next` three times), `settings`, `local` (the checkout brought up to the default branch just written, as a run's end does — `status` updated, ref_updated (another branch is checked out; only the branch moved), current, not_updated (left alone: `reason`, `files`, and `instead`, what to run) or failed (`reason`); `branch`, `from`, `to`, the `commits` that came in, and `contains_commit` when this call committed; tried on every call that gets this far, so calling again completes an update left undone, and never the reason for a non-zero exit), `runner` (the repository's `registered` runners with `name`, `status`, `labels`; this Mac's runner services in `local` with `session_create`, `env_token`, `path_has`; and `problems`, each `problem` — none (no runner with every label the job asks for), offline (this Mac's runner), not_local, session_create, path_missing — with `why` and the `fixes`; `error` instead of `problems` when the runners could not be listed), `warnings`, and `next` (the check run that proves the runner can start a worker). With --dry-run nothing is written and the checkout is not touched: `workflow_text`, `dispatcher_text`, `fires`, `settings`, `runner`. With --list: `schedules` (per schedule `name`, `file`, `cron` or `at`, `profile`, `state` active, disabled or unknown (GitHub has not registered the file yet), `dispatcher` loaded or missing, `stale_entry` with `stale_paths` and `fix` when a path in the workflow is gone, `last` job) and `orphans` (dispatchers whose workflow is gone).
Exits: 0 committed and installed, or listed — a dispatcher that failed to install is still 0 and says so in `dispatcher`; 1 refused or failed — run from inside a worker, not macOS, gh missing, not logged in or without the `workflow` scope, not a git checkout with a GitHub remote, a public repository without --public-ok, a NAME.yml that is not this schedule, two workflow files that both say they are this schedule, a workflow directory GitHub did not list, a new name that differs from another workflow file or schedule only by letter case or Unicode form (one file on a Mac) or that Windows reserves (con, nul, com1 …), a dispatcher or state on this Mac that belongs to another schedule, or GitHub refused the commit (branch protection: `instead` says how to commit it through a pull request); 2 the command line must change — a name that breaks the rule, a new schedule without a prompt, --profile or a time, both --cron and --at, a cron form or interval this skill does not take or one that never fires, an --at that has passed or is not zero-padded, a one-off whose time has passed called again without a new --at, --worktree with read-only, an unreadable --prompt-file or --schema, a prompt with a control character."""

SCHEDULE_EPILOG = f"""\
Time: --cron and --at are in this Mac's time zone, which launchd fires in and which the workflow's `timezone:` names; never convert them to UTC. --cron takes five numeric fields (minute hour day-of-month month day-of-week; `*`, `,`, `-`, `/`, no names like MON), fires at most every 5 minutes, and with both day fields restricted fires on either, as cron does. --at YYYY-MM-DDTHH:MM runs once; the run then disables its workflow and removes its dispatcher.
The Mac must be awake: a time missed in sleep runs once on wake. A job waits up to 24 hours for this repository's runner to be online and free, then fails; one runner runs one job at a time, so a long worker holds back the repository's other jobs.
Defaults: --model {SCHEDULE_DEFAULTS['model']}, --effort {SCHEDULE_DEFAULTS['effort']}, --timeout {SCHEDULE_DEFAULTS['timeout']}, --runs-on self-hosted; the job's own limit is --timeout plus 10 minutes.
Your checkout: when a run ends — completed, failed, timed out or cancelled — the job brings the default branch of the project checkout up to GitHub's, so what the worker merged there is on this Mac too. It fast-forwards the files when that branch is checked out, and otherwise moves only the branch. It never goes over anything of yours: a file you changed, an untracked or ignored file the update would replace, a commit only here, a merge or rebase in progress, a run working in the checkout itself, or an origin that is another repository leaves the checkout as it is, and the run's summary says why and what to run; the next run's end tries again. Hooks do not run, and git uses your own login, not the job's token. --no-pull leaves the checkout alone.
The runs, their pause, re-run, cancel and logs are GitHub's: `gh workflow disable|enable`, `gh run list|view|rerun|cancel`, or the repository's Actions page."""

UNSCHEDULE_DESC = """\
Remove a schedule: unload and delete its dispatcher LaunchAgent, and delete its workflow file from the default branch through the GitHub API. Past runs stay in the repository's Actions history, and the prompt stays in git history. A run of the schedule still live keeps the schedule's local state until it ends, without its definition, so it disables nothing.
Prints: one JSON line — `name`, `repo`, `dispatcher` (`status` removed, absent or failed, `label`, `plist`, `error`), `workflow` (`status` deleted, absent or failed, `path`, `commit`, `error`), `local` (as `schedule` gives it), and `note` when a live run kept the local state, or when this Mac's dispatcher or state under that name is another schedule's and was left alone.
Exits: 0 every part was tried (each says how it went); 1 refused before anything was removed — run from inside a worker, not macOS, gh missing, not logged in or without the `workflow` scope, not a git checkout with a GitHub remote, a repository gh cannot see, a workflow file of that name that is not this schedule (left alone), two workflow files that both say they are this schedule, or a name this Mac holds for another schedule; 2 the command line must change — no --name, or one no schedule can have (`schedule --help` says what a name holds)."""


class OneLinePerParagraph(argparse.HelpFormatter):
    """Each help paragraph and list item as one physical line, never re-wrapped; suppressed subcommands left out of the listing."""

    def _split_lines(self, text, width):
        return text.splitlines() or [""]

    def _fill_text(self, text, width, indent):
        return "\n".join(indent + line for line in text.splitlines())

    def _iter_indented_subactions(self, action):
        for sub in super()._iter_indented_subactions(action):
            if sub.help != argparse.SUPPRESS:
                yield sub

    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            action.metavar = "{" + ",".join(n for n, p in action.choices.items() if n in VISIBLE) + "}"
        return super()._format_action(action)


VISIBLE = ("start", "resume", "send", "batch", "status", "log", "result", "stop", "clean", "schedule", "unschedule", "doctor")


class ArgumentError(Exception):
    def __init__(self, message, command):
        super().__init__(message)
        self.command = command


class Parser(argparse.ArgumentParser):
    def error(self, message):
        name = self.prog.split()[-1] if " " in self.prog else None
        raise ArgumentError(message, name if name in VISIBLE or name in ("__supervise", "__scheduled") else None)


def positive(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number")
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def add_registry(p):
    p.add_argument("--project", metavar="DIR", help="resolve the registry (and, for start, the default working directory) from DIR instead of the current directory")
    p.add_argument("--runs-dir", metavar="DIR", help="use this registry directory as is")


def build_parser():
    root = Parser(prog="cli.py", description=ROOT_DESC, epilog=ROOT_EPILOG, formatter_class=OneLinePerParagraph)
    sub = root.add_subparsers(dest="command", metavar="COMMAND", parser_class=Parser)

    p = sub.add_parser("start", usage="cli.py start [PROMPT | --prompt-file FILE] [--profile P] [--model M] [--effort E] [--schema FILE] [options]", help="start a fresh worker session, detached", description=START_DESC, epilog=RUN_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("prompt", nargs="?", metavar="PROMPT", help="what the worker should do; or give --prompt-file, or pipe it on stdin")
    p.add_argument("--prompt-file", metavar="FILE", help="read the prompt from FILE")
    p.add_argument("--profile", choices=PROFILES, help=PROFILE_HELP)
    p.add_argument("--model", help=f"model alias or id passed to claude --model (default {DEFAULTS['model']}); a model claude does not know fails the run with its error")
    p.add_argument("--effort", choices=EFFORTS, help=f"reasoning effort (default {DEFAULTS['effort']})")
    p.add_argument("--schema", metavar="FILE", help="a JSON Schema file: the run's answer is structured output of that shape, which `result` prints as JSON")
    p.add_argument("--timeout", type=positive, metavar="SEC", help="stop the run after SEC seconds and record it timed_out")
    p.add_argument("--label", help="a short name that goes into the run id and listings")
    p.add_argument("--cwd", metavar="DIR", help="the worker's working directory (default: the top level of the current git checkout, or the current directory)")
    add_registry(p)

    p = sub.add_parser("resume", usage="cli.py resume REF [PROMPT | --prompt-file FILE] [--profile P] [--model M] [--effort E] [--schema FILE] [options]", help="run another turn on a session, detached", description=RESUME_DESC, epilog=RUN_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("ref", metavar="REF", help="a run id, a session id, or a unique prefix of either; or the id of a session this registry never saw (then --profile is required)")
    p.add_argument("prompt", nargs="?", metavar="PROMPT", help="what the worker should do next; or give --prompt-file, or pipe it on stdin")
    p.add_argument("--prompt-file", metavar="FILE", help="read the prompt from FILE")
    p.add_argument("--profile", choices=PROFILES, help="change the profile from this turn on (see start --help); required for a session the registry never saw")
    p.add_argument("--model", help="change the model from this turn on")
    p.add_argument("--effort", choices=EFFORTS, help="change the effort from this turn on")
    p.add_argument("--schema", metavar="FILE", help="a JSON Schema file for this and later turns' answers")
    p.add_argument("--timeout", type=positive, metavar="SEC", help="stop this run after SEC seconds and record it timed_out")
    p.add_argument("--label", help="a short name for this run (default: the session's last label)")
    p.add_argument("--cwd", metavar="DIR", help="the directory to resume in (default: where the session last ran); Claude Code finds a session by its project directory")
    add_registry(p)

    p = sub.add_parser("send", usage="cli.py send REF [MESSAGE | --message-file FILE] [--interrupt]", help="write a message into a live run", description=SEND_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("ref", metavar="REF", help="a run id, a session id, or a unique prefix of either")
    p.add_argument("message", nargs="?", metavar="MESSAGE", help="the message; or give --message-file, or pipe it on stdin")
    p.add_argument("--message-file", metavar="FILE", help="read the message from FILE")
    p.add_argument("--interrupt", action="store_true", help="priority `now`: end the running turn and start on this message")
    add_registry(p)

    p = sub.add_parser("batch", usage="cli.py batch --group NAME (--task PROMPT … | --tasks-file FILE) [--worktree] [--profile P] [options]", help="start several runs as one named group", description=BATCH_DESC, epilog=BATCH_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("--group", metavar="NAME", required=True, help="the group's name: lowercase letters, digits and hyphens, at most 40; reserved until `clean`")
    p.add_argument("--task", metavar="PROMPT", action="append", help="a member's prompt; repeat for several")
    p.add_argument("--tasks-file", metavar="FILE", help="members as JSON lines (see below), after the --task ones")
    p.add_argument("--worktree", action="store_true", help="give each fresh writing member its own git worktree (see below)")
    p.add_argument("--profile", choices=PROFILES, help="the members' default profile (see start --help)")
    p.add_argument("--model", help=f"the members' default model (default {DEFAULTS['model']})")
    p.add_argument("--effort", choices=EFFORTS, help=f"the members' default effort (default {DEFAULTS['effort']})")
    p.add_argument("--schema", metavar="FILE", help="the members' default JSON Schema file")
    p.add_argument("--timeout", type=positive, metavar="SEC", help="stop each member after SEC seconds")
    p.add_argument("--cwd", metavar="DIR", help="the members' default working directory (members with a cwd get no worktree)")
    add_registry(p)

    p = sub.add_parser("status", usage="cli.py status [--run REF | --group NAME]", help="list runs, or show one run or group", description=STATUS_DESC, epilog=STATUS_EPILOG, formatter_class=OneLinePerParagraph)
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--run", metavar="REF", help="a run id, a session id, or a unique prefix of either")
    sel.add_argument("--group", metavar="NAME", help="a group's name")
    add_registry(p)

    p = sub.add_parser("log", usage="cli.py log --run REF", help="what one run did, as text", description=LOG_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("--run", metavar="REF", required=True, help="a run id, a session id, or a unique prefix of either")
    add_registry(p)

    p = sub.add_parser("result", usage="cli.py result (--run REF | --group NAME) [--wait [--wait-timeout SEC]]", help="what a run or group concluded, now or once it ends", description=RESULT_DESC, epilog=RESULT_EPILOG, formatter_class=OneLinePerParagraph)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--run", metavar="REF", help="a run id, a session id, or a unique prefix of either")
    sel.add_argument("--group", metavar="NAME", help="a group's name")
    p.add_argument("--wait", action="store_true", help="block until the run ends or new attention appears")
    p.add_argument("--wait-timeout", type=positive, metavar="SEC", help="with --wait, give up after SEC seconds and print the partial result")
    add_registry(p)

    p = sub.add_parser("stop", usage="cli.py stop (--run REF [--run REF …] | --group NAME)", help="interrupt runs", description=STOP_DESC, formatter_class=OneLinePerParagraph)
    sel = p.add_mutually_exclusive_group(required=True)
    sel.add_argument("--run", metavar="REF", action="append", help="a run to stop; repeat for several")
    sel.add_argument("--group", metavar="NAME", help="stop every member of this group")
    add_registry(p)

    p = sub.add_parser("clean", usage="cli.py clean --group NAME [--force]", help="remove a group's worktrees and release its name", description=CLEAN_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("--group", metavar="NAME", required=True, help="the group to clean")
    p.add_argument("--force", action="store_true", help="also remove worktrees holding uncommitted, untracked or ignored work, discarding it; live work and branches with commits are still kept")
    add_registry(p)

    p = sub.add_parser("schedule", usage="cli.py schedule --name NAME [PROMPT | --prompt-file FILE] (--cron EXPR | --at YYYY-MM-DDTHH:MM) --profile P [options]\n       cli.py schedule --list", help="run a worker later or on a schedule, through this repository's runner", description=SCHEDULE_DESC, epilog=SCHEDULE_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("prompt", nargs="?", metavar="PROMPT", help="what the worker should do, standing on its own: nobody can answer it and nobody saw this conversation; or give --prompt-file. Required for a new schedule; given again, it replaces the recorded one")
    p.add_argument("--prompt-file", metavar="FILE", help="read the prompt from FILE; `-` reads stdin (stdin is read only then)")
    p.add_argument("--name", metavar="NAME", help="the schedule's name, used as given for the workflow file (.github/workflows/NAME.yml) and its title in Actions; a different name is a different workflow, and past runs stay with the old one. Up to 80 characters (an emoji counts as two); no `/` `\\` `:` `*` `?` `\"` `<` `>` `|`, no `${{`, no control or invisible character; not starting with `-` or a space, not ending with `.` or a space")
    when = p.add_mutually_exclusive_group()
    when.add_argument("--cron", metavar="EXPR", help="five numeric cron fields in this Mac's time zone, e.g. '0 3 * * *' (see below)")
    when.add_argument("--at", metavar="YYYY-MM-DDTHH:MM", help="run once at this local time (this Mac's time zone)")
    p.add_argument("--profile", choices=PROFILES, help="what the worker may do (see start --help); required for a new schedule, since nobody is there to widen it")
    p.add_argument("--model", help=f"model alias or id (default {SCHEDULE_DEFAULTS['model']})")
    p.add_argument("--effort", choices=EFFORTS, help=f"reasoning effort (default {SCHEDULE_DEFAULTS['effort']})")
    p.add_argument("--schema", metavar="FILE", help="a JSON Schema file: the run's answer is structured output of that shape, shown as JSON in the summary; its text goes into the workflow, so the file may go")
    p.add_argument("--timeout", type=positive, metavar="SEC", help=f"stop the run after SEC seconds and record it timed_out (default {SCHEDULE_DEFAULTS['timeout']})")
    wt = p.add_mutually_exclusive_group()
    wt.add_argument("--worktree", dest="worktree", action="store_const", const=True, help="run each time in a fresh git worktree of the local HEAD instead of the checkout (write and auto only); a worktree without changes is removed, and so is one whose commits are already on GitHub — on the default branch, or the head of a pull request merged into it — with what it left uncommitted kept in git (refs/claude/leftovers/…); one whose pull request is open, or with changes that are not on GitHub, is kept for you, and a later run's end looks at it again")
    wt.add_argument("--no-worktree", dest="worktree", action="store_const", const=False, help="run in the project checkout as it is when the job starts (the default)")
    pl = p.add_mutually_exclusive_group()
    pl.add_argument("--pull", dest="pull", action="store_const", const=True, help="when each run ends, whatever its outcome, fast-forward the project checkout's default branch to what GitHub holds, so what the worker merged there is here too (the default; see below)")
    pl.add_argument("--no-pull", dest="pull", action="store_const", const=False, help="leave the checkout as it is when a run ends: for a checkout someone works in on its default branch")
    p.add_argument("--runs-on", metavar="LABEL", action="append", help="a label the runner must have besides self-hosted; repeat for several")
    p.add_argument("--message", metavar="TEXT", help="the commit message (default: `Schedule Claude worker NAME: WHEN`)")
    p.add_argument("--public-ok", action="store_true", help="allow a public repository, whose Actions logs and summaries anyone can read and whose self-hosted runner runs code from anyone's pull request on this Mac")
    p.add_argument("--dry-run", action="store_true", help="write nothing: print the workflow and the dispatcher that would be written")
    p.add_argument("--list", action="store_true", help="list this repository's schedules instead")
    p.add_argument("--project", metavar="DIR", help="the project, a git checkout with a GitHub remote (default: the current directory)")

    p = sub.add_parser("unschedule", usage="cli.py unschedule --name NAME [--message TEXT] [--project DIR]", help="remove a schedule's dispatcher and workflow", description=UNSCHEDULE_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("--name", metavar="NAME", required=True, help="the schedule to remove")
    p.add_argument("--message", metavar="TEXT", help="the commit message (default: `Unschedule Claude worker NAME`)")
    p.add_argument("--project", metavar="DIR", help="the project (default: the current directory)")

    p = sub.add_parser("doctor", usage="cli.py doctor [--project DIR]", help="check the environment a run would start in", description=DOCTOR_DESC, formatter_class=OneLinePerParagraph)
    add_registry(p)

    p = sub.add_parser("__supervise", help=argparse.SUPPRESS)
    p.add_argument("--run-dir", required=True)

    # A scheduled job's two steps (K1), written into the workflow by `schedule`; both take the same flags so Finish knows what Run was told. The job's environment carries CLAUDE_SCHEDULE_MODE (run or check), _SOURCE (dispatcher or empty), _PROMPT and _SCHEMA.
    p = sub.add_parser("__scheduled", help=argparse.SUPPRESS)
    p.add_argument("step", choices=("run", "finish"))
    p.add_argument("--name", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--profile", choices=PROFILES, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", choices=EFFORTS, required=True)
    p.add_argument("--timeout", type=positive, required=True)
    when = p.add_mutually_exclusive_group(required=True)
    when.add_argument("--cron")
    when.add_argument("--at")
    p.add_argument("--timezone", required=True)
    p.add_argument("--worktree", action="store_true")
    p.add_argument("--no-pull", action="store_true")
    p.add_argument("--workflow")
    p.add_argument("--definition")
    return root


def read_text(value, path, command, what="prompt"):
    """The text given as a positional, a file, or on stdin — exactly one of them, and not empty."""
    flag = f"--{what}-file"
    if value is not None and path:
        raise Refusal(f"give the {what} once: {what.upper()} or {flag}", arguments=True, help=f"{command} --help")
    if path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise Refusal(f"{flag} {path}: {e.strerror or e}", arguments=True, help=f"{command} --help")
    elif value is not None:
        text = value
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = ""
    if not text.strip():
        raise Refusal(f"the {what} is empty", arguments=True, help=f"{command} --help")
    return text


def read_prompt(args, command):
    return read_text(args.prompt, args.prompt_file, command)


def schedule_prompt(args):
    """K24: the prompt from PROMPT or --prompt-file, stdin only for `--prompt-file -`; None when neither is given (a schedule called again keeps its prompt)."""
    if args.prompt is not None and args.prompt_file:
        raise Refusal("give the prompt once: PROMPT or --prompt-file", arguments=True, help="schedule --help")
    if args.prompt_file == "-":
        text = sys.stdin.read()
    elif args.prompt_file:
        try:
            text = Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise Refusal(f"--prompt-file {args.prompt_file}: {e.strerror or e}", arguments=True, help="schedule --help")
    elif args.prompt is not None:
        text = args.prompt
    else:
        return None
    if not text.strip():
        raise Refusal("the prompt is empty", arguments=True, help="schedule --help")
    return text


def schedule_schema(path):
    """The --schema file's JSON object as compact text (K22), or None."""
    if not path:
        return None
    try:
        obj = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as e:
        raise Refusal(f"--schema {path}: {e.strerror or e}", arguments=True, help="schedule --help")
    except ValueError as e:
        raise Refusal(f"--schema {path} is not JSON: {e}", arguments=True, help="schedule --help")
    if not isinstance(obj, dict):
        raise Refusal(f"--schema {path} must hold a JSON object", arguments=True, help="schedule --help")
    return json.dumps(obj, ensure_ascii=False)


def base_dir(args):
    return str(Path(args.project).expanduser().resolve()) if getattr(args, "project", None) else os.getcwd()


def run_flags(args):
    flags = {"profile": args.profile, "model": args.model, "effort": args.effort, "schema": args.schema, "cwd": None}
    if args.cwd:
        cwd = Path(args.cwd).expanduser()
        if not cwd.is_dir():
            raise Refusal(f"--cwd {args.cwd} is not a directory", arguments=True, help=f"{args.command} --help")
        flags["cwd"] = str(cwd.resolve())
    return flags


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def dispatch(args):
    c = args.command
    if c == "start":
        reply = start(prompt=read_prompt(args, "start"), cwd=base_dir(args), flags=run_flags(args), label=args.label, timeout=args.timeout, runs_dir=args.runs_dir)
        emit(reply)
        return EXIT_REFUSED if reply.get("state") == "failed" else 0
    if c == "resume":
        reply = resume(ref=args.ref, prompt=read_prompt(args, "resume"), cwd=base_dir(args), flags=run_flags(args), label=args.label, timeout=args.timeout, runs_dir=args.runs_dir)
        emit(reply)
        return EXIT_REFUSED if reply.get("state") == "failed" else 0
    if c == "send":
        emit(send(ref=args.ref, message=read_text(args.message, args.message_file, "send", "message"), interrupt=args.interrupt, cwd=base_dir(args), runs_dir=args.runs_dir))
        return 0
    if c == "batch":
        defaults = {"profile": args.profile, "model": args.model, "effort": args.effort, "schema": args.schema, "timeout": args.timeout, "cwd": run_flags(args)["cwd"]}
        if args.schema and not Path(args.schema).expanduser().is_file():
            raise Refusal(f"--schema {args.schema} is not a file", arguments=True, help="batch --help")
        emit(batch(name=args.group, task_args=args.task, tasks_file=args.tasks_file, defaults=defaults, cwd=base_dir(args), use_worktrees=args.worktree, runs_dir=args.runs_dir))
        return 0
    if c == "clean":
        emit(clean(name=args.group, cwd=base_dir(args), force=args.force, runs_dir=args.runs_dir))
        return 0
    if c == "status":
        emit(status(cwd=base_dir(args), ref=args.run, group=args.group, runs_dir=args.runs_dir))
        return 0
    if c == "log":
        sys.stdout.write(log(cwd=base_dir(args), ref=args.run, runs_dir=args.runs_dir))
        return 0
    if c == "result":
        if args.wait_timeout and not args.wait:
            raise Refusal("--wait-timeout needs --wait", arguments=True, help="result --help")
        sys.stdout.write(result(cwd=base_dir(args), ref=args.run, group=args.group, wait_for=args.wait, wait_timeout=args.wait_timeout, runs_dir=args.runs_dir))
        return 0
    if c == "stop":
        emit(stop(refs=args.run or [], group=args.group, cwd=base_dir(args), runs_dir=args.runs_dir))
        return 0
    if c == "schedule":
        if args.list:
            emit(schedules(cwd=base_dir(args)))
            return 0
        if not args.name:
            raise Refusal("--name is required", arguments=True, help="schedule --help")
        flags = {"prompt": schedule_prompt(args), "schema": schedule_schema(args.schema), "cron": args.cron, "at": args.at, "profile": args.profile, "model": args.model, "effort": args.effort, "timeout": args.timeout, "worktree": args.worktree, "pull": args.pull, "runs_on": args.runs_on}
        emit(schedule(name=args.name, flags=flags, cwd=base_dir(args), dry_run=args.dry_run, public_ok=args.public_ok, message=args.message))
        return 0
    if c == "unschedule":
        emit(unschedule(name=args.name, cwd=base_dir(args), message=args.message))
        return 0
    if c == "doctor":
        reply = doctor(cwd=base_dir(args), runs_dir=args.runs_dir)
        emit(reply)
        return 0 if reply["ok"] else EXIT_BLOCKED
    if c == "__supervise":
        return supervise(args.run_dir)
    if c == "__scheduled":
        spec = {"name": args.name, "project": args.project, "settings": {"profile": args.profile, "model": args.model, "effort": args.effort, "timeout": args.timeout}, "cron": args.cron, "at": args.at, "timezone": args.timezone, "worktree": args.worktree, "pull": not args.no_pull, "workflow": args.workflow, "definition": args.definition}
        step = scheduled_run if args.step == "run" else scheduled_finish
        code = step(spec, dict(os.environ), lambda text: (sys.stdout.write(text), sys.stdout.flush()))
        return code
    raise Refusal("no command given", arguments=True, help="--help")


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return dispatch(args)
    except ArgumentError as e:
        emit({"error": str(e), "help": f"{e.command} --help" if e.command else "--help"})
        return EXIT_ARGUMENTS
    except Refusal as e:
        emit(e.reply())
        return EXIT_ARGUMENTS if e.arguments else EXIT_REFUSED
    except OSError as e:
        # A registry or file the command cannot write is an outcome to report, not a traceback.
        emit({"error": f"{e.strerror or e}: {e.filename}" if e.filename else str(e)})
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
