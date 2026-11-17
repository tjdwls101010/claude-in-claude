# Claude in Claude

The `claude` skill (`.claude/skills/claude/`) of the `headless-workers` plugin: headless Claude Code workers as managed subagents.

- `SKILL.md` carries only judgment the CLI's help cannot; flags, outputs and exit codes live in `scripts/cli.py --help`, which is the contract.
- The package's map is the docstring of `scripts/claude/__init__.py`; `tests/test_structure.py` keeps its layering.
- Tests: `python3 -m unittest discover -s tests` (fake `claude`, `gh` and `launchctl` on PATH, about 7 minutes). Real claude, from `tests/`: `CLAUDE_SKILL_REAL=1 python3 -m unittest smoke_real_claude`. Real schedules, from `tests/` (commits to and runs on a private repository of yours, see CONTRIBUTING.md): `CLAUDE_SKILL_REAL=1 CLAUDE_SKILL_REAL_GITHUB=1 CLAUDE_SKILL_REAL_SCHEDULE_PROJECT=<checkout> python3 -m unittest smoke_real_schedule`. Headless contrast of SKILL.md: `python3 tests/e2e/run_e2e.py --out .tmp/e2e`.
- Expected values come from real captures in `tests/support/fixtures/`, never from the code under test.
