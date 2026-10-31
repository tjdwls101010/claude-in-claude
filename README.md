# Claude in Claude

**Run headless Claude Code workers as managed, steerable background subagents from inside Claude Code.**

[Overview](#1-overview) · [Features](#2-features) · [Quick Start](#3-quick-start) · [Usage](#4-usage) · [Project Status](#5-project-status)

## 1. Overview

Claude Code's own subagents, agent teams and workflows run inside the session that started them: the orchestrator cannot look at a worker's progress, cannot follow several of them separately, and does not notice when one stops on a permission prompt, a question or an API retry — it just waits. This skill gives an orchestrating Claude the missing handle. It starts the installed `claude` CLI headless (`claude -p --input-format stream-json --output-format stream-json`) under a detached supervisor that holds the worker's stdin and stdout, and answers at once with a run id. From then on the orchestrator can read a compact log, wait for the result with one call that also wakes it when the worker stalls, steer the worker with a message while it runs, stop it, resume it, and run several as one group.

Workers inherit your whole Claude Code environment — CLAUDE.md files, skills, hooks, plugins, MCP servers, memory — and your subscription login; every turn is pinned to one of three permission profiles the skill defines.

## 2. Features

- **Start, then a handle.** `start` returns a `run_id` and the exact `result --wait` command to run in the background.
- **Profiles.** `read-only` runs any shell command inside Claude Code's sandbox (writes only to TMPDIR and `~/.cache`, network only to hosts your settings allow), so it can run tests without touching your tree; `write` edits inside its directory; `auto` leaves each call to Claude Code's auto-mode classifier. Settings of yours that widen a profile are reported as `profile_exceptions`.
- **Waiting that notices trouble.** `result --wait` returns when the run ends, or early when it stalls for 10 minutes, retries the API for 2 minutes, hits a rejected rate limit, or keeps running after its answer.
- **Steering.** `send` writes a message into a running worker (`--interrupt` ends its current turn).
- **Resume with the same rules.** `resume` re-sends the profile, model, effort and schema every turn, because a resumed `claude -p` restores only the model.
- **Groups and worktrees.** `batch` starts several workers as one named group; `--worktree` gives each writer its own git worktree from your local HEAD; `clean` removes them only when that loses nothing.
- **Structured results.** `--schema` makes the answer JSON of a given shape.
- **Diagnosis.** `doctor` checks claude's version, login, the sandbox and your current usage limits without starting a worker.

## 3. Quick Start

Requirements: macOS (Linux is untested), Claude Code 2.1.314 or newer logged in with your claude.ai subscription, [`uv`](https://docs.astral.sh/uv/), git.

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

Pre-approve the skill and its one command form in `~/.claude/settings.json` (`permissions.allow`), with the path where the skill lives:

```json
"Skill(claude)",
"Bash(uv run \"/Users/you/.claude/skills/claude/scripts/cli.py\" *)"
```

For the plugin install the skill is `Skill(headless-workers:claude)` and the path is the plugin's install directory; `doctor` prints the exact `invocation` to approve.

First run:

```bash
uv run ~/.claude/skills/claude/scripts/cli.py doctor
```

It exits 0 when claude, its version, the login and the registry are fine, and prints the account's current usage limits.

## 4. Usage

Inside Claude Code, ask for a worker in plain words ("have a Claude worker run the tests read-only and tell me what fails"); the skill tells Claude how to call it. By hand:

```bash
CLI=~/.claude/skills/claude/scripts/cli.py
uv run "$CLI" start "Run the test suite and report failures. Change nothing." --profile read-only --model haiku
uv run "$CLI" send <run_id> "Also say how long the suite took."   # while it runs
uv run "$CLI" result --run <run_id> --wait          # blocks until done or attention
uv run "$CLI" log --run <run_id>
uv run "$CLI" batch --group review --worktree --task "Fix A" --task "Fix B"
uv run "$CLI" result --group review --wait
uv run "$CLI" clean --group review
```

Every command prints one JSON line (or text, where its `--help` says so); `uv run "$CLI" <command> --help` documents its output and exit codes. Runs are recorded in `.claude-runs/` of the repository's main checkout, which ignores itself.

## 5. Project Status

Version 0.1.0. Verified on macOS with Claude Code 2.1.314 and a Max subscription. Not included: Linux and Windows verification, workers that message each other directly (run rounds with `batch` and `resume` instead), budget and turn limits, forking sessions, image input, and a worktree for a single run. See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Licensed under the Apache License 2.0.
