# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-11-17

Scheduling: a worker that runs unattended at a set time on this Mac, with GitHub Actions as its record and controls.

### Added

- `schedule` commits `.github/workflows/claude-NAME.yml` to the repository's default branch through the GitHub API and installs a LaunchAgent on this Mac that starts it on time (`gh workflow run … -f source=dispatcher`); GitHub's own cron in the file is a late backup whose duplicates are skipped. Each run is a job on the repository's self-hosted runner: the worker starts as `start` would, the job holds it to its end, and a summary on the run page shows the prompt, the answer, the changes, the activity and how to continue it. `--cron` (five numeric fields) or `--at` (once, then the workflow turns itself off), in this Mac's time zone; `--profile` is required; `--worktree` gives each writing run its own checkout; `--dry-run`; `--list`. A read-only run that failed, timed out or lost its supervisor is tried once more by the next automatic trigger for the same time.
- `unschedule` removes a schedule's dispatcher and workflow file (only files the skill wrote).
- The reply's `runner` names what would keep a run from starting on this Mac — no runner, offline, not installed here, a service that cannot read the Claude login, tools missing from the runner's PATH — with why and how to fix it.
- `doctor` has a `schedule` section: platform, gh, the project's GitHub repository and its runners. Scheduling problems are warnings, never blockers.
- Private repositories only, unless `--public-ok`: a public repository's Actions summaries are public and its self-hosted runner runs code from anyone's pull request.

### Changed

- Every worker's `claude` now starts behind a small `/bin/sh` gate and becomes `claude` with `exec` (same pid, argv and process group) only after the supervisor has recorded its pid and found no stop request.
- A group of one (`batch` with a single task) is no longer told that other members work in parallel.

### Fixed

- `stop` on a run that was still starting — published, its supervisor not yet launched, or `claude` launched but its pid not yet recorded — let the worker start and do its work anyway. Now nothing of it runs, and the never-delivered prompt is listed in `undelivered`.

## [0.1.0] — 2026-10-31

First release: headless Claude Code workers as managed subagents, as the `claude` skill of the `headless-workers` plugin.

### Added

- `start` launches `claude -p --input-format stream-json --output-format stream-json` under a detached supervisor and answers with a handle once claude reports its first init, so a start that fails at once (not logged in, a bad flag) says so in its reply.
- Three permission profiles re-sent on every turn: `read-only` (dontAsk, no edit tools, every shell command inside Claude Code's sandbox that can write only TMPDIR and `~/.cache`), `write` (acceptEdits in the same sandbox) and `auto` (Claude Code's classifier). Settings that widen a profile are reported as `profile_exceptions`.
- `result --wait` returns when the run ends, or early on new attention: no event for 10 minutes, API retries for 2 minutes, a rejected rate limit, claude still running 2 minutes after its answer, or a turn that ended with no reply and no hook notice.
- The answer is the last result after the last delivered message that is neither a background follow-up nor ended by a hook; the header names which messages it answers.
- `send` writes a message into a live run (priority `next`, or `now` with `--interrupt`); `resume` continues a session as a new run with its profile, model, effort and schema; `stop` signals the run's process group (SIGINT, SIGTERM, SIGKILL).
- `batch` starts several runs as one named group, with `--worktree` giving each fresh writer Claude Code's own worktree from your local HEAD; `result --group`, `status --group`, `stop --group`; `clean` removes worktrees only when that loses nothing.
- `log` prints one line per event; `status` lists runs, groups and the newest rate limit; `doctor` checks claude's version (2.1.314 or newer), login, the sandbox and the account's usage limits without starting a worker.
- Workers inherit the user's whole Claude Code environment with background tasks off, the parent session's identity removed, and Monitor, SendMessage, PushNotification, CronCreate, RemoteTrigger and this skill itself disallowed.
