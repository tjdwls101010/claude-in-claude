"""Claude Code workers as managed subagents. The tree, by kind:

Features (one per reason to change):
    runs/        start, resume, send and stop; creating a run and the detached supervisor that drives one `claude -p` process
    batch/       several runs as one named group, worktree isolation for its members, and clean
    observe/     status, log and result, including `result --wait` and the attention that ends a wait early
    doctor.py    the environment a run would start in, and the account's usage limits

Systems (formats someone else owns):
    claude_cli/  everything about the Claude Code CLI: argv and profiles, the worker's environment, stream-json in and out, version, auth, settings files
    git/         the git CLI: top level, main checkout, worktrees, branches

Store:
    registry/    <main checkout>/.claude-runs: run directories and meta.json, session and run locks, the send inbox, group manifests

Shared:
    errors.py    Refusal, the one error a command turns into an exit code
    util.py      time, text trimming, process liveness, the skill's own invocation string, timings

Imports run feature → store → system → shared; the one edge between features is batch → runs.
"""
