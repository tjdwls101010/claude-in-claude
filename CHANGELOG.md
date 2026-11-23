# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

What a schedule leaves on GitHub reaches the checkout on this Mac.

### Added

- When a scheduled run ends — completed, failed, timed out or cancelled — its Finish step fast-forwards the default branch of the project checkout to what GitHub holds, so a pull request the worker merged there is on this Mac too. The files move when that branch is checked out; otherwise only the branch does. Nothing of yours is gone over: a file you changed that the incoming commits change, an untracked or ignored file they would replace, a commit only here, a merge or rebase in progress, a run working in the checkout itself, or an origin that is another repository leaves it as it is, and the summary's warning says why and what to run. Repository hooks do not run, and git uses your own login rather than the job's token.
- The summary has a **Local checkout** row and a **From GitHub** list of the commits that came in.
- `schedule --no-pull` turns this off for a schedule (`--pull` turns it back on). It is on by default, also for schedules committed before it: their workflow files do not change.
- `schedule` and `unschedule` bring the checkout up the same way right after their commit; the reply's `local` says how it went (`contains_commit` when they committed), and calling again completes an update left undone.
- A scheduled worker is told that the job updates the checkout after it, so it does not try to pull from its worktree.
- A `--worktree` run's worktree is removed once its commits are on GitHub — on the default branch, or the head of a pull request merged into it — even with something left uncommitted in it: that is first kept in git as two commits under `refs/claude/leftovers/<group>-<n>` (the index, and every changed, untracked and ignored file; not `.worktreeinclude` copies), and the summary says how to bring it back. Its branches go too when they point at those commits (`git fetch origin pull/<n>/head` brings them back). A worktree whose pull request is open stays, and the end of a later run of the repository's schedules looks at it again, so a pull request merged by hand the next day still gets its worktree removed. Groups made before this version, groups you made with `batch`, and worktrees that changed after their run ended are not touched. A branch that was there before the run, and the default branch, are never deleted; a file `.worktreeinclude` names is never stored.

### Changed

- `remote_url` reads the remote's URL as configured, before `url.*.insteadOf` rewriting: a rewrite to a mirror no longer makes `schedule` and `doctor` miss the GitHub repository.
- A worktree run's summary says "the worker did not touch your checkout" instead of "your checkout is not touched", since the job now may.

### Fixed

- `clean` (with or without `--force`) no longer removes a worktree with a directory git cannot read: git skipped it with only a warning, so what it held looked like nothing.

## [0.3.0] — 2026-11-22

A schedule's name is the person's: used as given for its workflow file and its title in Actions.

### Changed

- `schedule --name` takes a name as given — underscores, capitals, any script, emoji, spaces (e.g. `261128_SS_외국인순매수`) — up to 80 characters (an emoji counts as two), in Unicode NFC. It refuses only what breaks something, and says what: `/`, `${{`, a leading `-` or space, characters Windows cannot check out (`\ : * ? " < > |`, a trailing `.` or space), control and invisible characters.
- A new schedule's workflow is `.github/workflows/NAME.yml` and its title in Actions is `NAME`; neither carries the `claude-` / `claude · ` prefix any more.
- Schedules 0.2.0 committed keep their file `claude-NAME.yml` and title `claude · NAME`, keep running and are changed in place when `schedule --name NAME` is called again (once committed even when nothing else changed, as the title is now quoted). Renaming means scheduling the new name and unscheduling the old one; to GitHub that is another workflow, and past runs stay with the old one.
- A new name that differs from another workflow file or schedule only by letter case or Unicode form is refused (on a Mac the two would share one file, state and dispatcher), as is a name Windows reserves (`con`, `nul`, `com1` …).
- `schedule --list` finds schedules by the skill's header whatever the file is called; each row has `file`, and `state` is `unknown` for a file GitHub has not registered yet.
- A hand-written `claude-X.yml` no longer blocks `--name X`, which now writes `X.yml`.
- A `--worktree` run's group and branch are an ASCII slug of the name (`261128-ss-<run id>-1`, or `schedule-<run id>-1` for a name with no ASCII letter or digit).
- The summary's title shows the name's own characters, and the commands it, the reply and the job's annotations print quote the name and file for the shell.

### Fixed

- `unschedule`, and a one-off's Finish step, could remove the dispatcher plist or local state of another schedule whose path is the same on this Mac (names differing only by case, or labels two repositories share). They now touch only what is this schedule's own, and `schedule` refuses to install over another's.
- Workflow file names and the branch are percent-encoded on their way to `gh api`, which read `#`, `?` and `%` in them as URL syntax.

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
