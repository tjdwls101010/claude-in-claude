# Claude in Claude

**Run headless Claude Code workers as managed, steerable background subagents from inside Claude Code.**

[Overview](#1-overview) · [Features](#2-features) · [Quick Start](#3-quick-start) · [Usage](#4-usage) · [Scheduling](#5-scheduling) · [Project Status](#6-project-status)

## 1. Overview

Claude Code's own subagents, agent teams and workflows run inside the session that started them: the orchestrator cannot look at a worker's progress, cannot follow several of them separately, and does not notice when one stops on a permission prompt, a question or an API retry — it just waits. This skill gives an orchestrating Claude the missing handle. It starts the installed `claude` CLI headless (`claude -p --input-format stream-json --output-format stream-json`) under a detached supervisor that holds the worker's stdin and stdout, and answers at once with a run id. From then on the orchestrator can read a compact log, wait for the result with one call that also wakes it when the worker stalls, steer the worker with a message while it runs, stop it, resume it, and run several as one group.

Workers inherit your whole Claude Code environment — CLAUDE.md files, skills, hooks, plugins, MCP servers, memory — and your subscription login; every turn is pinned to one of three permission profiles the skill defines.

## 2. Features

- **Start, then a handle.** `start` returns a `run_id` and the exact `result --wait` command to run in the background.
- **Profiles.** `read-only` runs any shell command inside Claude Code's sandbox (writes only to TMPDIR and `~/.cache`, network only to hosts your settings allow), so it can run tests without touching your tree; `write` edits inside its directory; `auto` leaves each call to Claude Code's auto-mode classifier. Settings of yours that widen a profile are reported as `profile_exceptions`.
- **Waiting that notices trouble.** `result --wait` returns when the run ends, or early when it stalls for 10 minutes, retries the API for 2 minutes, hits a rejected rate limit, or keeps running after its answer.
- **Steering.** `send` writes a message into a running worker (`--interrupt` ends its current turn).
- **Resume with the same rules.** `resume` re-sends the profile, model, effort and schema every turn, because a resumed `claude -p` restores only the model.
- **Groups and worktrees.** `batch` starts several workers as one named group; `--worktree` gives each fresh writer (a new `write` or `auto` member without a directory of its own) its own git worktree from your local HEAD; `clean` removes them only when that loses nothing.
- **Structured results.** `--schema` makes the answer JSON of a given shape.
- **Scheduling.** `schedule` runs a worker unattended at a set time, once or on a cron, on this Mac through the repository's self-hosted runner, with GitHub Actions as its record and controls; `unschedule` removes it.
- **Diagnosis.** `doctor` checks claude's version, login, the sandbox and your current usage limits without starting a worker, and whether this project is ready for scheduling.

## 3. Quick Start

Requirements: macOS (Linux is untested), Claude Code 2.1.314 or newer logged in with your claude.ai subscription, [`uv`](https://docs.astral.sh/uv/), git. Scheduling also needs [`gh`](https://cli.github.com/) and a self-hosted runner (see [Scheduling](#5-scheduling)).

Install as a plugin:

```bash
claude plugin marketplace add tjdwls101010/claude-in-claude
claude plugin install headless-workers@claude-in-claude
```

Or link the skill folder for development:

```bash
git clone https://github.com/tjdwls101010/claude-in-claude.git
ln -s "$PWD/claude-in-claude/.claude/skills/claude" ~/.claude/skills/claude
```

The skill's folder is then, for the plugin, `~/.claude/plugins/cache/claude-in-claude/headless-workers/<version>/.claude/skills/claude`, and for the link, `~/.claude/skills/claude`. Pre-approve the skill and its one command form in `~/.claude/settings.json` (`permissions.allow`), with that folder written out:

```json
"Skill(headless-workers:claude)",
"Bash(uv run \"/Users/you/.claude/plugins/cache/claude-in-claude/headless-workers/0.4.0/.claude/skills/claude/scripts/cli.py\" *)"
```

For the link install the skill is `Skill(claude)` and the path `/Users/you/.claude/skills/claude/scripts/cli.py`. The rule must name the path the way the skill runs it; `doctor` prints it as `invocation`.

First run, with `SKILL_DIR` set to the skill's folder:

```bash
uv run "$SKILL_DIR/scripts/cli.py" doctor
```

It exits 0 when claude, its version, the login and the registry are fine, and prints the account's current usage limits.

## 4. Usage

Inside Claude Code, ask for a worker in plain words ("have a Claude worker run the tests read-only and tell me what fails"); the skill tells Claude how to call it. By hand:

```bash
CLI="$SKILL_DIR/scripts/cli.py"
uv run "$CLI" start "Run the test suite and report failures. Change nothing." --profile read-only --model haiku
uv run "$CLI" send <run_id> "Also say how long the suite took."   # while it runs
uv run "$CLI" result --run <run_id> --wait          # blocks until done or attention
uv run "$CLI" log --run <run_id>
uv run "$CLI" batch --group review --worktree --task "Fix A" --task "Fix B"
uv run "$CLI" result --group review --wait
uv run "$CLI" clean --group review
```

Every command prints one JSON line (or text, where its `--help` says so); `uv run "$CLI" <command> --help` documents its output and exit codes. Runs are recorded in `.claude-runs/` of the repository's main checkout, which ignores itself.

## 5. Scheduling

A worker can also run unattended at a set time — every night, every Monday, or once tomorrow — on this Mac, with GitHub Actions as its record and controls.

```
schedule ──▶ GitHub API ──▶ .github/workflows/NAME.yml on the default branch   (the definition; GitHub's cron is a late backup)
         └─▶ launchctl  ──▶ ~/Library/LaunchAgents/claude-schedule.OWNER-REPO.NAME.plist   (starts the workflow on time)

on time:  LaunchAgent ── gh workflow run ──▶ GitHub ──▶ this repository's self-hosted runner (this Mac)
            Run:    the worker starts as `start` would, under your login, and the job holds it to its end
            Finish: stops whatever is still alive, records what changed, brings your checkout's default
                    branch up to GitHub's, writes the run's summary
```

It needs:

1. a **private** GitHub repository for the project (a public one shows every summary to anyone, and its self-hosted runner runs code from anyone's pull request; `--public-ok` overrides);
2. a **self-hosted runner** of that repository installed as a service on this Mac (`./svc.sh install`; on a personal account a runner serves one repository);
3. a runner service that can **read your Claude login** — the default service runs in a security session of its own and cannot; the `schedule` reply's `runner.problems` names this and both ways to fix it;
4. the Mac **awake** at the time (a time missed in sleep runs once on wake), and `gh` logged in with the `workflow` scope.

A first schedule, by hand:

```bash
uv run "$CLI" schedule --name nightly-review "Review yesterday's commits on main and report what looks risky, with file and line." --cron "0 3 * * *" --profile read-only
gh workflow run nightly-review.yml -f mode=check     # the reply's `next`: proves the runner can start a worker
gh workflow run nightly-review.yml                   # a run now, without waiting for 03:00
uv run "$CLI" schedule --list
uv run "$CLI" unschedule --name nightly-review
uv run "$CLI" schedule --name 270225_NVDA_Q4 "Read NVDA's Q4 results and update notes/NVDA.md." --at 2027-02-25T09:00 --profile write --worktree
```

`--name` is used as given for the workflow file and for its title in Actions, so the second schedule is `270225_NVDA_Q4.yml` there.

Times are in this Mac's time zone. Each run's page on GitHub shows a summary: the outcome, the trigger and the tree the worker saw, alerts (failures, denied tool calls), the prompt, the worker's answer, what changed, its activity (trimmed when long), and the commands to continue the session on your Mac; the run is also in `.claude-runs/` like any other, so `status`, `log`, `result` and `resume` work on it. `--at YYYY-MM-DDTHH:MM` runs once and then turns its workflow off. `--worktree` gives each writing run its own checkout of your local HEAD. Pausing is disabling the workflow (`gh workflow disable`); re-running and cancelling are GitHub's too.

What a run merges on GitHub reaches this Mac by itself: when a run ends, whatever its outcome, the job fast-forwards the default branch of your checkout to GitHub's (and `schedule` and `unschedule` do the same right after their commit). It never goes over anything of yours — a file you changed that the incoming commits also change, an untracked or ignored file they would replace, a commit only here, a merge or rebase in progress, or a run working in the checkout itself leave the checkout as it is, and the run's summary says why and what to run; the next run's end tries again. So a worker told to open and merge a pull request needs no "then pull" in its prompt (from its worktree it could not anyway). `--no-pull` turns this off for a schedule whose checkout you work in on its default branch.

A `--worktree` run's worktree goes once its commits are on GitHub — on the default branch, or the head of a pull request merged into it — even when the worker left something uncommitted, which is kept in git first (`refs/claude/leftovers/<group>-1`; `git worktree add <path> <commit>` brings it back), and its branches go with it. While its pull request is open the worktree stays, and the end of a later run of any of the repository's schedules looks at it again, unless something in it changed since. `git for-each-ref refs/claude/leftovers` lists what was kept; `git update-ref -d <ref>` drops one.

## 6. Project Status

Version 0.4.0. Verified on macOS with Claude Code 2.1.314 and a Max subscription; scheduling with gh 2.103 and a self-hosted runner on a private repository. Not included: Linux and Windows verification, scheduling anywhere but macOS and launchd, cron names (`MON`) and intervals under 5 minutes, workers that message each other directly (run rounds with `batch` and `resume` instead), budget and turn limits, forking sessions, image input, and a worktree for a single run. See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Licensed under the Apache License 2.0.
