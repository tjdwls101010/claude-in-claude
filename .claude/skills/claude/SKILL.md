---
name: claude
description: "Start headless Claude Code workers (claude -p sessions) in the background and manage them like subagents: a handle at once, progress you can read, steering with send, stopping and resuming it, several workers as one group, waiting for and collecting text or JSON-schema results, checking usage limits, and scheduling a worker to run later or recurringly on this Mac, with GitHub Actions as its record. Use when work should go to another Claude session you can watch, steer and collect, when several Claude workers should run in parallel, when a long task should run while you do something else, or unattended at a set time. Triggers include: claude worker, headless claude, claude -p worker, background claude, schedule a claude worker, scheduled claude, 클로드 작업자, 클로드한테 시켜, 클로드로 병렬, 백그라운드 클로드, 작업자 띄워, 예약 작업자, 매일 ~시에 돌려, 정기 실행. Not for questions about Claude Code features, the built-in Agent tool, agent teams, claude --bg, Claude Code's own cloud or Desktop scheduled tasks or /loop, or the Claude API and SDK."
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
---

# Claude workers as managed subagents

Call it as `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …`, written out in full on one line: the pre-approval matches the command text, so a path kept in a shell variable, a `$(…)` or a pipe added to the call, or a command continued with `\` asks for permission every time. Replies are made to be read as printed. `--help` lists the commands, and `<command> --help` owns every flag, default, refusal, output field and exit code.

## Handing work over

**The profile decides what a worker can do, and so what it can show you.** `read-only` reads anything and runs any shell command inside a sandbox, so a review or an investigation can bring back what its tests and builds printed, not only what it read; `write` when it must change files in its directory; `auto` only when it needs the network or to write outside it. Your own settings can widen a profile, and the reply's `profile_exceptions` names how.

**A worker runs in your whole Claude Code environment**: CLAUDE.md files, skills, hooks, plugins, MCP servers, memory. That is input you did not write into the prompt, so say in the prompt what matters for this task.

**Git is yours.** Workers are told to leave commits, branches, pushes and merges to you and to report what they changed; ask in the prompt when you want one of those.

**`resume` or a fresh `start`.** A resumed session brings what it already worked out and replays a transcript that grows every turn; a fresh start knows nothing. Continue when the new work builds on the old understanding, start fresh when it doesn't.

**A verification loop stops on a predicate the work can satisfy.** "Until nothing new comes back" never ends, because each new look finds something. Stop on something the work runs out of: no finding reachable in ordinary use, a named property that holds, a `--schema` answer over a set you can bound.

| Yours | Here | Not available |
|---|---|---|
| `Agent` | `start`, then its reply's `next.command` in the background | — |
| `Workflow` `parallel()` | `batch` with several `--task` | — |
| a word to a running subagent | `send`; `--interrupt` ends its current turn | — |
| stopping one | `stop` | — |
| teammates messaging each other, a shared task list | — | run rounds: `batch`, collect, then resume each member with the others' findings |
| a scheduled or recurring agent | `schedule` (runs here, through this repository's runner) | — |

## Several workers at once

A batch is for when N workers should be one name you watch, collect and stop. **Decide isolation when you start.** Members share your tree by default; when two may edit the same files, start them with `--worktree`, which gives each fresh writer a checkout of your local HEAD: none of your uncommitted changes, nothing git ignores except what `.worktreeinclude` copies. **N workers spend your subscription limits N times**, so read `doctor`'s `quota` before a wide batch. **A group outlives the session**: `status` lists groups, `result --group` collects them, moving changes out of worktrees is yours, and `clean` finishes.

## Waiting, steering and collecting

**A detached worker announces nothing.** Run the reply's `next.command` in a background Bash call, as given; its exit notifies you, and the output file it points to is the result. Then use the turn for other work or hand it back; don't invent work to fill the wait.

**A wait that comes back before the end is a decision point.** Its `attention` says why (stalled, retrying, rate-limited, finishing, possibly blocked) and what the worker was doing: wait again with its `next`, correct course with `send`, or `stop` it.

**A result read is not a result checked.** Check the claims and changes that matter before relying on them. `permission_denials` is what the worker could not do, so decide whether that needs another profile; `files_edited` misses files a shell command wrote.

**If this is your only turn**, run `next.command` in the foreground with `--wait-timeout` added and the Bash call's timeout above it; if the budget runs out first, hand back the run id and say the work is unfinished.

## Scheduling a worker

**Every run draws on the subscription's limits with nobody watching**, for as long as the schedule stands, so how often it runs and its `--timeout` are a cost the person sets. **Some fixes are the owner's to choose**: scheduling in a public repository (`--public-ok`) lets anyone's pull request run code on this Mac, and where the reply's `runner.problems` offers more than one fix, such as how the runner's service gets the Claude login, each exposes that login differently.

## When something goes wrong

- `doctor` checks the environment without starting a worker. A run that fails says why in `status --run <id>` (`error`, `stderr_tail`).
- `mode_mismatch` means the worker did not start in its profile's permission mode (auto on a model without auto mode): treat what it may do as unknown.
- To look inside a worker's session yourself, once it has ended: `claude --resume <session_id>` in its directory.
- A scheduled run that ends red says why in its summary's first alert, or, when there is no summary, in the job's step log. `Not logged in` there is the runner's service, not the worker: `doctor`'s `schedule.runners.problems` says what to change.
- If the command itself is not found: without `uv` nothing here runs, and installing it is the fix; with `uv`, the skill's path did not resolve: `ls "${CLAUDE_SKILL_DIR}/scripts"`.
