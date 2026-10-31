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

from claude.claude_cli import PROFILES, VERSION_FLOOR_TEXT
from claude.errors import Refusal
from claude.observe import LISTING_ROWS, STALL_SECONDS, log, result, status
from claude.runs import DEFAULTS, EFFORTS, start, stop, supervise

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

STATUS_DESC = f"""\
What the registry knows: every live run plus the {LISTING_ROWS} newest, or one run in full.
Prints: one JSON line. With no selector: `registry`, `live` (run ids), `runs` (a short row each: `run_id`, `session_id`, `state`, `label`, `group`, `profile`, `model`, `idle_seconds`, `error`, `attention`, `last_message`), `runs_truncated`, `groups`, and the newest `rate_limit` any run observed. With --run: that run's full row — the above plus `stored_state`, `permission_mode`, `mode_mismatch`, `cwd`, `created`, `ended`, `elapsed_seconds`, `exit_code`, `in_progress` (calls without a result yet), `tasks_open`, `permission_denials`, `files_edited`, `tool_calls`, `messages`, `unanswered`, `undelivered`, `stdin_open`, `retrying_since`, `rate_limit`, `cost_usd`, `usage`, `profile_exceptions`, `stderr_tail` for a failure, `still_writing` when claude outlived its supervisor, `events`.
Exits: 0 answered; 1 refused — no such run, an ambiguous prefix, or a meta.json that does not parse; 2 the command line must change."""

STATUS_EPILOG = f"""\
States:
  starting     published; claude has not reported its init
  running      claude has the turn
  retrying     running, and the last event is an API retry (`retrying_since` says since when)
  stalled      starting or running with no event for {STALL_SECONDS} s; advisory, nothing is killed — read `in_progress` beside it
  finishing    the answer is in and stdin is closed, but claude is still running something
  completed    ended: the last answer succeeded
  failed       ended: claude exited non-zero, the answer is an error, or a hook ended the only message (`error` says which)
  interrupted  ended: stopped
  timed_out    ended: its --timeout passed
  orphaned     ended: its supervisor died without recording an outcome; `still_writing` says claude is still running
`attention` lists what needs a look now: `stalled`, `retrying` for 120 s, `rate_limited` (a rejected rate limit), `finishing` for 120 s, `possibly_blocked`."""

LOG_DESC = """\
What one run did, read from its events.
Prints: text, one line per event — `init model=… mode=… cwd=…` (again when either changes), `msg <text>` with the whole message, `bash exit=<n> out=<bytes>B <command>` with the head and tail of the output indented beneath a failure, `edit|write|read <path>`, `grep|glob <pattern>`, `fetch <url>`, `search <query>`, `skill <name>`, `agent <type> <description> tools=<n> out=<bytes>B`, `mcp <server>/<tool> ok|error`, `denied <tool> <input>`, `sent <priority> <message>`, `task <status> <description>`, `retry attempt=<a>/<max> error=<kind> status=<http>`, `ratelimit <status> 5h=<%> 7d=<%>` when the status changes, `compact`, `result <subtype> turns=<n> terminal=<reason> cost=$<x>` (with `origin=task-notification` for a background follow-up), `running <tool> <summary>` for calls still without a result — then `run=<id> state=<state>`.
Exits: 0 printed; 1 refused — no such run; 2 the command line must change — no --run."""

RESULT_DESC = """\
What a run concluded: at once (partial while it is live), or with --wait once it ends or needs attention.
Prints: a JSON header line — `run_id`, `session_id`, `state`, `exit_code`, `error`, `attention`, `answered` (the messages the answer replies to), `unanswered`, `last_message_unanswered`, `answer_unconfirmed` (claude did not say which message it answered), `blocked_by_hook`, `last_message_blocked`, `possibly_blocked`, `permission_denials`, `files_edited`, `files_edited_note`, `tool_calls`, `usage`, `cost_usd`, `followups` (background follow-up turns, not the answer), `mode_mismatch`, `profile_exceptions`, `message_bytes`, and `note` and `next` while the run is live — then the final message. A --schema run prints one indented JSON document instead, whose `json` is the structured output (null while live).
Exits: 0 printed, whatever the run's state, also when --wait-timeout passes; 1 refused — no such run, or a --schema run that ended without structured output (`message` carries its text); 2 the command line must change — no --run, --wait-timeout without --wait or not positive."""

RESULT_EPILOG = f"""\
--wait returns early when attention appears that was not there when it began: no event for {STALL_SECONDS} s (`stalled`), API retries for 120 s (`retrying`), a rejected rate limit (`rate_limited`), claude still running 120 s after the answer (`finishing`), or a turn that ended with no reply and no hook notice (`possibly_blocked`). The header's `attention` says which, with what the run was doing; its `next` waits again for something new. Nothing is stopped for it.
`files_edited` lists edit-tool calls; files a shell command wrote are not in it."""

STOP_DESC = """\
Stop runs through their recorded process groups, never by name: SIGINT, then SIGTERM after 10 s, then SIGKILL 3 s later. SIGINT first lets Claude Code end the turn so the session can be resumed.
Prints: one JSON line — `stopped`, an entry per run with `run_id`, `session_id`, `signals_sent` and `state` (`interrupted` for a run that was live; one that had ended keeps its state, with `note`).
Exits: 0 every run was tried; 1 refused — run from inside a worker, or no such run; 2 the command line must change — no --run."""


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


VISIBLE = ("start", "status", "log", "result", "stop")


class ArgumentError(Exception):
    def __init__(self, message, command):
        super().__init__(message)
        self.command = command


class Parser(argparse.ArgumentParser):
    def error(self, message):
        name = self.prog.split()[-1] if " " in self.prog else None
        raise ArgumentError(message, name if name in VISIBLE or name == "__supervise" else None)


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

    p = sub.add_parser("status", usage="cli.py status [--run REF]", help="list runs, or show one run in full", description=STATUS_DESC, epilog=STATUS_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("--run", metavar="REF", help="a run id, a session id, or a unique prefix of either")
    add_registry(p)

    p = sub.add_parser("log", usage="cli.py log --run REF", help="what one run did, as text", description=LOG_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("--run", metavar="REF", required=True, help="a run id, a session id, or a unique prefix of either")
    add_registry(p)

    p = sub.add_parser("result", usage="cli.py result --run REF [--wait [--wait-timeout SEC]]", help="what a run concluded, now or once it ends", description=RESULT_DESC, epilog=RESULT_EPILOG, formatter_class=OneLinePerParagraph)
    p.add_argument("--run", metavar="REF", required=True, help="a run id, a session id, or a unique prefix of either")
    p.add_argument("--wait", action="store_true", help="block until the run ends or new attention appears")
    p.add_argument("--wait-timeout", type=positive, metavar="SEC", help="with --wait, give up after SEC seconds and print the partial result")
    add_registry(p)

    p = sub.add_parser("stop", usage="cli.py stop --run REF [--run REF …]", help="interrupt runs", description=STOP_DESC, formatter_class=OneLinePerParagraph)
    p.add_argument("--run", metavar="REF", action="append", required=True, help="a run to stop; repeat for several")
    add_registry(p)

    p = sub.add_parser("__supervise", help=argparse.SUPPRESS)
    p.add_argument("--run-dir", required=True)
    return root


def read_prompt(args, command):
    if args.prompt is not None and args.prompt_file:
        raise Refusal("give the prompt once: PROMPT or --prompt-file", arguments=True, help=f"{command} --help")
    if args.prompt_file:
        try:
            text = Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise Refusal(f"--prompt-file {args.prompt_file}: {e.strerror or e}", arguments=True, help=f"{command} --help")
    elif args.prompt is not None:
        text = args.prompt
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = ""
    if not text.strip():
        raise Refusal("the prompt is empty", arguments=True, help=f"{command} --help")
    return text


def base_dir(args):
    return str(Path(args.project).expanduser().resolve()) if getattr(args, "project", None) else os.getcwd()


def run_flags(args):
    flags = {"profile": args.profile, "model": args.model, "effort": args.effort, "schema": args.schema, "cwd": None}
    if args.cwd:
        cwd = Path(args.cwd).expanduser()
        if not cwd.is_dir():
            raise Refusal(f"--cwd {args.cwd} is not a directory", arguments=True, help="start --help")
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
    if c == "status":
        emit(status(cwd=base_dir(args), ref=args.run, runs_dir=args.runs_dir))
        return 0
    if c == "log":
        sys.stdout.write(log(cwd=base_dir(args), ref=args.run, runs_dir=args.runs_dir))
        return 0
    if c == "result":
        if args.wait_timeout and not args.wait:
            raise Refusal("--wait-timeout needs --wait", arguments=True, help="result --help")
        sys.stdout.write(result(cwd=base_dir(args), ref=args.run, wait_for=args.wait, wait_timeout=args.wait_timeout, runs_dir=args.runs_dir))
        return 0
    if c == "stop":
        emit(stop(refs=args.run, cwd=base_dir(args), runs_dir=args.runs_dir))
        return 0
    if c == "__supervise":
        return supervise(args.run_dir)
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


if __name__ == "__main__":
    sys.exit(main())
