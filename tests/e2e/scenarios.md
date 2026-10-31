# S6 scenarios

Each scenario runs once with the draft SKILL.md and once with the control (frontmatter and the invocation paragraph only), in a fresh project, with a headless orchestrator `claude -p --model sonnet --setting-sources project,local` that has only this skill. Workers run on haiku with the user's whole environment, since the skill's CLI starts them. `run_e2e.py` holds the prompts and the checks; this file says what each scenario is for.

1. **delegate** — hand an investigation to a worker and answer from its result. Checks: one-line calls, `next` run in the background, no polling loop, the answer uses the worker's finding.
2. **batch** — three independent read-only checks as one group, then one summary. Checks: `batch` with three tasks rather than three `start`s, `result --group --wait`, the summary covers all three.
3. **steer** — a worker sent the wrong way is corrected with `send` while it runs. Checks: `send` used before the worker ended, the final answer follows the correction.
4. **denied** — a worker that cannot do part of its task (a write outside its directory under `write`). Checks: the orchestrator reports the denial or failure instead of claiming success.
5. **read-only tests** — find a bug by running the tests without changing files. Checks: `--profile read-only`, the worker ran the tests, the project tree is unchanged apart from startup artifacts.
