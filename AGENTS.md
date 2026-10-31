# Claude in Claude

The `claude` skill (`.claude/skills/claude/`) of the `headless-workers` plugin: headless Claude Code workers as managed subagents.

- `SKILL.md` carries only judgment the CLI's help cannot; flags, outputs and exit codes live in `scripts/cli.py --help`, which is the contract.
- The package's map is the docstring of `scripts/claude/__init__.py`; `tests/test_structure.py` keeps its layering.
- Tests: `python3 -m unittest discover -s tests` (fake `claude` on PATH, about 4 minutes). Real claude: `CLAUDE_SKILL_REAL=1 python3 -m unittest tests/smoke_real_claude.py`. Headless contrast of SKILL.md: `python3 tests/e2e/run_e2e.py --out .tmp/e2e`.
- Expected values come from real captures in `tests/support/fixtures/`, never from the code under test.
