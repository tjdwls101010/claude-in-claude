"""Inside a GitHub Actions job on a self-hosted runner: what the job's environment says (which run, attempt and event, where the step summary and outputs go), taking the job's handles away from a worker (K9), and the workflow commands a step prints — annotations, and stopping the runner from reading commands in text it did not write (K21)."""

from __future__ import annotations

# Files and tokens through which a step changes later steps, the step summary or the repository: a worker must not hold them (K9). RUNNER_TRACKING_ID stays, so the runner can still clean up whatever a broken job leaves.
JOB_HANDLES = ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY", "GH_TOKEN", "GITHUB_TOKEN")


def job_context(env):
    """The job this process runs in, from its environment, or None outside a GitHub Actions run: `run_id`, `attempt` (1 for the first try), `job` (`<run id>-<attempt>`, unique per attempt), `event` (`schedule`, `workflow_dispatch`, …), `repository` (`owner/name`), `url` (the run's page), `summary_path` and `output_path` (None when the runner gave none)."""
    run_id = env.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    attempt = int(env.get("GITHUB_RUN_ATTEMPT") or 1)
    server = (env.get("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")
    repository = env.get("GITHUB_REPOSITORY")
    return {
        "run_id": run_id,
        "attempt": attempt,
        "job": f"{run_id}-{attempt}",
        "event": env.get("GITHUB_EVENT_NAME"),
        "repository": repository,
        "url": f"{server}/{repository}/actions/runs/{run_id}" + (f"/attempts/{attempt}" if attempt > 1 else "") if repository else None,
        "summary_path": env.get("GITHUB_STEP_SUMMARY") or None,
        "output_path": env.get("GITHUB_OUTPUT") or None,
    }


def scrub_job_env(env):
    """`env` without the job's handles (JOB_HANDLES)."""
    return {k: v for k, v in env.items() if k not in JOB_HANDLES}


def write_summary(path, text):
    """Append `text` to the step summary file; OSError when it cannot be written."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def write_output(path, values):
    """Append `name=value` lines to the step output file; values are single-line."""
    with open(path, "a", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={'' if v is None else str(v).replace(chr(10), ' ')}\n")


def _escape_data(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text):
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotation(level, title, message):
    """The workflow command that makes an annotation on the run's page: `level` is `error`, `warning` or `notice`."""
    return f"::{level} title={_escape_property(title)}::{_escape_data(message)}"


def stop_commands(token):
    """The line after which the runner reads no workflow command until `resume_commands(token)`."""
    return f"::stop-commands::{token}"


def resume_commands(token):
    return f"::{token}::"
