# Security Policy

## Reporting a Vulnerability

If you believe you have found a security vulnerability in Claude in Claude, please report it privately — **do not open a public GitHub issue**. Use GitHub's private vulnerability reporting: open the [Security tab](https://github.com/tjdwls101010/claude-in-claude/security) of this repository, click **Report a vulnerability**, and fill in the advisory form.

Reports of particular interest:

- **Profile escalation** — a `read-only` or `write` worker writing or reaching the network beyond its profile, across a `resume` or otherwise, other than through settings `profile_exceptions` reports.
- **`stop` or `clean` acting on something they do not own** — signalling a process group that is not the run's claude, or removing a worktree or branch that holds work.
- **Registry tampering** — `.claude-runs/` content steering a later command (a printed command, a signal, a removal) somewhere it should not go.
- **Command injection** in how `scripts/cli.py` builds the worker's argv or the commands it prints.

## What to Include

The command you ran, the profile, what you expected and what happened, `doctor` output, and the run's `events.jsonl` and `meta.json` with anything private removed.

## Scope

Workers run under your own Claude Code login and settings; the profiles restrict them further but do not sandbox your hooks, MCP servers or WebFetch, which follow your permission rules. A worker on `auto` is reviewed by Claude Code's classifier, not by this project.
