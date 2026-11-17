# Security Policy

## Reporting a Vulnerability

If you believe you have found a security vulnerability in Claude in Claude, please report it privately — **do not open a public GitHub issue**. Use GitHub's private vulnerability reporting: open the [Security tab](https://github.com/tjdwls101010/claude-in-claude/security) of this repository, click **Report a vulnerability**, and fill in the advisory form.

Reports of particular interest:

- **Profile escalation** — a `read-only` or `write` worker writing or reaching the network beyond its profile, across a `resume` or otherwise, other than through settings `profile_exceptions` reports.
- **`stop` or `clean` acting on something they do not own** — signalling a process group that is not the run's claude, or removing a worktree or branch that holds work.
- **Registry tampering** — `.claude-runs/` content steering a later command (a printed command, a signal, a removal) somewhere it should not go.
- **Command injection** in how `scripts/cli.py` builds the worker's argv or the commands it prints.
- **A schedule doing more than its reply says** — `schedule` or `unschedule` writing a file other than `.github/workflows/claude-NAME.yml` or a LaunchAgent other than `claude-schedule.OWNER-REPO.NAME`, a prompt or path reaching the workflow as something other than text, or a scheduled worker holding the job's token or file commands.

## What to Include

The command you ran, the profile, what you expected and what happened, `doctor` output, and the run's `events.jsonl` and `meta.json` with anything private removed.

## Scope

Workers run under your own Claude Code login and settings; the profiles restrict them further but do not sandbox your hooks, MCP servers or WebFetch, which follow your permission rules. A worker on `auto` is reviewed by Claude Code's classifier, not by this project.

## Scheduling

- **What a schedule leaves.** On GitHub, a workflow file committed straight to the default branch (no pull request), holding the prompt, the profile and the project's path; the commit stays in history after `unschedule`. Every run's summary shows the prompt, the answer, the changes and the worker's activity to whoever can read the repository's Actions. On this Mac, a LaunchAgent `~/Library/LaunchAgents/claude-schedule.OWNER-REPO.NAME.plist` and its log under `~/Library/Logs/claude-schedule/`, and the runs in `.claude-runs/`.
- **Public repositories are refused** unless `--public-ok`: their summaries are public, and a self-hosted runner of a public repository runs code from anyone's pull request on this Mac.
- **The job's token.** A recurring schedule's workflow asks for no permissions (`permissions: {}`); a one-off asks for `actions: write` only, which its Finish step uses to disable its own workflow.
- **What the worker does not get.** Before the worker starts, the job's handles are removed from its environment: `GITHUB_TOKEN`, `GH_TOKEN` and the file commands (`GITHUB_ENV`, `GITHUB_OUTPUT`, `GITHUB_PATH`, `GITHUB_STATE`, `GITHUB_STEP_SUMMARY`), and the runner stops reading workflow commands from text the worker wrote. Its directory under the runner's temp folder is not hidden: a worker that can write outside its project (`auto`, or settings that widen a profile) can find those files there and change the job's later steps or its summary.
- **The runner's login.** For a worker to run, the runner's service must reach your Claude login, either by running in your login session or through a token in the runner's `.env`; anything the runner runs, including other workflows of that repository, can then use it.
