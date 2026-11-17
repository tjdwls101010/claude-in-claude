"""Claude Code workers as managed subagents. The tree, by kind:

Features (one per reason to change):
    runs/        start, resume, send and stop; creating a run and the detached supervisor that drives one `claude -p` process
    batch/       several runs as one named group, worktree isolation for its members, and clean
    observe/     status, log and result, including `result --wait` and the attention that ends a wait early; `snapshot` and `wait_ended`, the structure they render, for callers that read a run without parsing text
    schedule/    a scheduled job's Run and Finish steps on a self-hosted runner, the slot a trigger fills, and the summary it posts
    doctor.py    the environment a run would start in, and the account's usage limits

Systems (formats someone else owns):
    claude_cli/  everything about the Claude Code CLI: argv and profiles, the worker's environment, stream-json in and out, version, auth, settings files
    git/         the git CLI: top level, main checkout, worktrees, branches, a checkout's state before and after a run
    github/      GitHub Actions inside a job: its environment, the handles a worker must not hold, step summaries, outputs and workflow commands

Store:
    registry/    <main checkout>/.claude-runs: run directories and meta.json, session and run locks, the send inbox, group manifests, and .schedules/<name>/ (slots and each job's hand-over)

Shared:
    errors.py    Refusal, the one error a command turns into an exit code
    util.py      time, text trimming, process liveness, the skill's own invocation string, timings

Imports run feature → store → system → shared; the edges between features are batch → runs and schedule → runs, batch, observe.
"""
