# Contributing to Claude in Claude

This project is a Claude Code plugin (`headless-workers`) holding one skill, `claude`, backed by a Python standard-library CLI run with `uv run`. Bug fixes, tests and documentation are welcome; please open an issue before adding a runtime dependency or a new command, since the CLI is deliberately stdlib-only and its surface small.

## 1. Layout

```
.claude/skills/claude/
├── SKILL.md          judgment the help cannot carry
└── scripts/
    ├── cli.py        the only entry point: parser, help, dispatch, exit codes
    └── claude/       the only package; its __init__.py docstring is the map
        ├── runs/ batch/ observe/ schedule/ doctor.py   features
        ├── claude_cli/ git/ github/ launchd/            formats someone else owns
        ├── registry/                                    .claude-runs/ state
        └── errors.py util.py                            shared
tests/                 suite, fake claude, gh and launchctl, fixtures, S5 smokes, S6 e2e
```

Imports run feature → store → system → shared, with `batch → runs` and `schedule → runs, batch, observe` the only edges between features; every unit is used through its interface (`__all__`). `tests/test_structure.py` enforces both, and that nothing edits `sys.path`.

## 2. Development

Requirements: Python 3.11+ on PATH for the tests, `uv`, git, and for the real-claude tiers Claude Code 2.1.314+ logged in. There is no build step. To use a checkout as your live skill:

```bash
ln -s "$PWD/.claude/skills/claude" ~/.claude/skills/claude
```

## 3. Tests

- **Suite** — `python3 -m unittest discover -s tests` from the repository root. It drives the real CLI as a subprocess with `tests/support/fake_claude/claude`, `fake_gh/gh` and `fake_launchctl/launchctl` first on PATH, so nothing reaches GitHub or launchd; the fakes' answers come from real captures in `tests/support/fixtures/` (`github/` for gh), the fake claude's docstring lists the `[[fake:…]]` markers that choose a scenario, and the fake gh's lists the `world.json` it simulates. About 7 minutes.
- **S5, real claude** — from `tests/`: `CLAUDE_SKILL_REAL=1 python3 -m unittest smoke_real_claude -v`. Workers run on haiku with your own environment and subscription; projects go under `.tmp/`.
- **S5, real schedules** — from `tests/`: `CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1 CLAUDE_SKILL_REAL_SCHEDULE_PROJECT=<checkout> python3 -m unittest smoke_real_schedule -v`, with a checkout of a private repository of your own whose self-hosted runner runs as a service on this Mac and can read the Claude login. It commits `smoke-*.yml` and `Smoke_*.yml` workflows to that repository's default branch, installs `claude-schedule.*.smoke-*` and `claude-schedule.*.Smoke_*` LaunchAgents, runs real jobs and workers on haiku, commits files through the Contents API, opens and squash-merges a pull request (`smoke-pr-*`), and removes its schedules at the end, also when it fails; the commits stay in the repository's history. The checkout must be on its default branch with nothing in the way, since what lands on GitHub is brought into it. About 35 minutes.
- **S6, headless contrast of SKILL.md** — `python3 tests/e2e/run_e2e.py --out .tmp/e2e` runs ten scenarios (6–10 schedule through the fake gh and launchctl, writing and removing only `someone-project` files under `~/Library`) with the draft SKILL.md and with a control (frontmatter and the invocation paragraph only), through a sonnet orchestrator that loads nothing of yours but the skill. Use it before changing SKILL.md: a sentence that changes no behaviour is a candidate to cut.

Expected values come from captures, documentation or hand-worked examples, never from the code under test; a new behaviour gets a test that fails without it.

## 4. Pull requests

One logical change per commit; behaviour and structure in separate commits. Say in the PR what you ran and what it printed. `--help` must match what the code does — `tests/test_cli_contract.py` and `tests/test_install.py` check the parts they can.
