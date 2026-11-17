"""`schedule`, `unschedule` and `schedule --list`: a schedule is a workflow file committed to the repository's default branch through the GitHub API, which is its definition and GitHub's backup cron, plus a LaunchAgent on this Mac that starts it on time (K12). The two writes go to two systems, so each reply says how each went rather than hiding half of a failure; both happen under the schedule's lock, as does a one-off's Finish deciding to disable it (K8)."""

from __future__ import annotations

import os
from pathlib import Path

from claude.errors import Refusal
from claude.git import main_checkout, remote_url, toplevel
from claude.github import GitHubError, delete_workflow, gh_status, list_workflows, local_runners, parse_spec, read_workflow, render_workflow, repo_facts, repo_from_remote, runner_problems, runners, set_workflow_enabled, workflow_file, workflow_state, write_workflow
from claude.launchd import agent_state, calendar_entries, install_agent, list_agents, remove_agent, render_agent, supported, system_timezone
from claude.registry import latest_job, read_meta, remove_schedule_state, resolve_runs_dir, schedule_lock, schedule_runs_live, write_definition
from claude.runs import refuse_inside_worker
from claude.util import entry_path, iso

from .execute import clock, local_time
from .spec import check_name, dispatcher_label, fields_of, merge
from .times import fire_times

PREFIX = "claude-"


def dispatcher_log(repo, name):
    owner, rname = repo.split("/", 1)
    return str(Path(os.path.expanduser("~")) / "Library" / "Logs" / "claude-schedule" / f"{owner}-{rname}.{name}.log")


def dispatcher_argv(gh, repo, file, branch):
    return [gh, "workflow", "run", file, "--repo", repo, "--ref", branch, "-f", "source=dispatcher"]


def _gh_ready(need_workflow_scope=True):
    status = gh_status()
    if status["error"]:
        raise Refusal(status["error"], instead="install the GitHub CLI and run `gh auth login`" if not status["path"] else "gh auth login")
    if need_workflow_scope and "workflow" not in status["scopes"]:
        raise Refusal("gh's token lacks the `workflow` scope, which committing a workflow file needs", instead="gh auth refresh -s workflow")
    return status


def _project(cwd):
    """(main checkout, owner/repo) of the project at `cwd`; Refusal when it is not a git checkout with a GitHub remote."""
    top = toplevel(cwd)
    if not top:
        raise Refusal(f"{cwd} is not in a git repository; a schedule lives in the repository's GitHub Actions")
    project = main_checkout(cwd) or top
    url = remote_url(project)
    repo = repo_from_remote(url)
    if not repo:
        raise Refusal(f"the repository at {project} has no GitHub remote named origin ({url or 'none'}); a schedule lives in the repository's GitHub Actions")
    return project, repo


def _facts(repo):
    try:
        return repo_facts(repo)
    except GitHubError as e:
        raise Refusal(f"GitHub does not show {repo} to gh: {e.message}")


def _existing(repo, file, branch):
    """(workflow read from the default branch or None, its spec or None). Refusal when the file is there but this skill did not write it."""
    try:
        current = read_workflow(repo, file, branch)
    except GitHubError as e:
        raise Refusal(f"could not read .github/workflows/{file}: {e.message}")
    if current is None:
        return None, None
    try:
        spec = parse_spec(current["text"])
    except ValueError as e:
        raise Refusal(f".github/workflows/{file} has a spec line that does not parse ({e}); fix or delete the file")
    if spec is None:
        raise Refusal(f".github/workflows/{file} exists and was not written by this skill; choose another --name")
    return current, spec


def _runner(repo, tools):
    try:
        registered = runners(repo)
    except GitHubError as e:
        return {"registered": None, "local": local_runners(repo), "problems": [], "error": f"the runners could not be listed: {e.message}"}
    local = local_runners(repo)
    return {"registered": registered, "local": local, "problems": runner_problems(registered, local, tools)}


def _fires(spec, now):
    out = {"timezone": spec["timezone"], "cron": spec.get("cron"), "at": spec.get("at"), "next": [local_time(t, spec["timezone"]) for t in fire_times(spec, now, 3)]}
    return out


def schedule(*, name, flags, cwd, dry_run=False, public_ok=False, message=None):
    """Create or change the schedule `name` (see `schedule --help`)."""
    refuse_inside_worker()
    check_name(name)
    if not supported():
        raise Refusal("schedules need launchd, so macOS: its LaunchAgent starts each run on time")
    timezone = system_timezone()
    if not timezone:
        raise Refusal("this Mac's time zone could not be read from /etc/localtime")
    gh = _gh_ready()
    project, repo = _project(cwd)
    facts = _facts(repo)
    if not facts["private"] and not public_ok:
        raise Refusal(f"{repo} is public: its Actions logs and step summaries — the prompt, the answer and the activity — are public, and a self-hosted runner on a public repository runs code anyone's pull request brings onto this Mac", instead="schedule in a private repository, or pass --public-ok if you accept both")
    branch = facts["default_branch"]
    file = workflow_file(name)
    registry = resolve_runs_dir(project)
    label = dispatcher_label(repo, name)
    log = dispatcher_log(repo, name)
    now = clock()

    def build(current, recorded):
        """The spec and workflow text to commit; when nothing but the definition would change, the committed ones, so an unchanged schedule is not committed again."""
        spec = merge({**flags, "name": name}, recorded, timezone=timezone, project=project, cli=entry_path(), now=now)
        if current is not None:
            same = {**spec, "definition": recorded.get("definition")}
            if render_workflow(same) == current["text"]:
                return same, current["text"]
        return spec, render_workflow(spec)

    current, recorded = _existing(repo, file, branch)
    spec, text = build(current, recorded)
    calendar = calendar_entries(fields_of(spec))
    argv = dispatcher_argv(gh["path"], repo, file, branch)
    runner = _runner(repo, ("uv", "claude", "gh") if spec.get("at") else ("uv", "claude"))
    settings = {k: spec[k] for k in ("profile", "model", "effort", "timeout", "worktree", "runs_on")}
    if dry_run:
        return {"name": name, "repo": repo, "dry_run": True, "workflow_path": f".github/workflows/{file}", "workflow_text": text, "dispatcher_label": label, "dispatcher_text": render_agent(label, argv, calendar, log), "fires": _fires(spec, now), "settings": settings, "runner": runner}

    warnings = []
    commit_message = message or (f"Schedule Claude worker {name}: " + (f"once at {spec['at']} ({timezone})" if spec.get("at") else f"{spec['cron']} ({timezone})"))
    with schedule_lock(registry, name):
        status = "unchanged"
        commit = url = None
        if current is None or current["text"] != text:
            for attempt in (1, 2):
                try:
                    done = write_workflow(repo, file, text, commit_message, branch, sha=(current or {}).get("sha"))
                    status, commit, url = "committed", done["commit"], done["url"]
                    break
                except GitHubError as e:
                    if not e.conflict or attempt == 2:
                        raise Refusal(f"GitHub refused the commit to {branch}: {e.message}", instead=f"{entry_path()} schedule … --dry-run prints the workflow; commit it through a pull request" if e.status == 422 else None)
                    # Another schedule call changed the file first: merge onto what it committed and try once more (K12).
                    current, recorded = _existing(repo, file, branch)
                    spec, text = build(current, recorded)
                    if current is not None and current["text"] == text:
                        break
        url = url or (current or {}).get("url")
        was_disabled = False
        try:
            state = workflow_state(repo, file)
            if state and state != "active":
                set_workflow_enabled(repo, file, True)
                was_disabled = True
        except GitHubError as e:
            warnings.append(f"whether the workflow is enabled could not be checked or changed: {e.message}; `gh workflow enable {file} --repo {repo}` enables it")
        dispatcher = install_agent(label, argv, calendar, log)
        if dispatcher["status"] != "installed":
            warnings.append("the dispatcher was not installed, so only GitHub's backup cron starts this schedule, often late; run the same command again")
        write_definition(registry, name, spec["definition"])
    if spec.get("at"):
        warnings.append("GitHub's own cron can run a one-off hours late or not at all; the dispatcher on this Mac starts it on time while the Mac is awake (on wake if it slept), and the run disables its workflow afterwards")
    return {
        "name": name,
        "repo": repo,
        "workflow": {"status": status, "path": f".github/workflows/{file}", "url": url, "commit": commit, "was_disabled": was_disabled},
        "dispatcher": dispatcher,
        "fires": _fires(spec, now),
        "settings": settings,
        "runner": runner,
        "warnings": warnings,
        "next": {"command": f"gh workflow run {file} --repo {repo} -f mode=check", "why": "a check job on the runner is the only proof the service can log in and start a worker; read its summary on the run page"},
    }


def unschedule(*, name, cwd, message=None):
    """Remove the schedule `name`: its dispatcher and its workflow file (see `unschedule --help`)."""
    refuse_inside_worker()
    check_name(name)
    if not supported():
        raise Refusal("schedules need launchd, so macOS")
    _gh_ready()
    project, repo = _project(cwd)
    facts = _facts(repo)
    branch = facts["default_branch"]
    file = workflow_file(name)
    registry = resolve_runs_dir(project)
    reply = {"name": name, "repo": repo}
    with schedule_lock(registry, name):
        reply["dispatcher"] = remove_agent(dispatcher_label(repo, name))
        try:
            current = read_workflow(repo, file, branch)
            if current is None:
                reply["workflow"] = {"status": "absent", "path": f".github/workflows/{file}"}
            else:
                done = delete_workflow(repo, file, message or f"Unschedule Claude worker {name}", branch, current["sha"])
                reply["workflow"] = {"status": "deleted", "path": f".github/workflows/{file}", "commit": done["commit"]}
        except GitHubError as e:
            reply["workflow"] = {"status": "failed", "path": f".github/workflows/{file}", "error": e.message}
        live = schedule_runs_live(registry, name)
        if live:
            # The live run's Finish still needs its job's hand-over; only the definition goes, so it will not disable anything (K8).
            write_definition(registry, name, None)
            reply["note"] = f"run(s) {', '.join(live)} of this schedule are still live, so its local state is kept until they end; `gh run cancel <id> --repo {repo}` cancels a job"
        else:
            remove_schedule_state(registry, name)
    return reply


def schedules(*, cwd):
    """The repository's schedules (see `schedule --list`)."""
    refuse_inside_worker()
    _gh_ready(need_workflow_scope=False)
    project, repo = _project(cwd)
    facts = _facts(repo)
    registry = resolve_runs_dir(project)
    out, names = [], set()
    try:
        found = list_workflows(repo, PREFIX)
    except GitHubError as e:
        raise Refusal(f"the workflows could not be listed: {e.message}")
    for w in found:
        try:
            current = read_workflow(repo, w["file"], facts["default_branch"])
            spec = parse_spec(current["text"]) if current else None
        except (GitHubError, ValueError):
            spec = None
        if not spec:
            continue
        name = spec["name"]
        names.add(name)
        last = latest_job(registry, name)
        row = {"name": name, "cron": spec.get("cron"), "at": spec.get("at"), "timezone": spec.get("timezone"), "profile": spec.get("profile"), "state": "active" if w["state"] == "active" else "disabled", "dispatcher": "loaded" if agent_state(dispatcher_label(repo, name)) == "loaded" else "missing"}
        stale = [p for p in (spec.get("cli"), spec.get("project")) if p and not Path(p).exists()]
        row["stale_entry"] = bool(stale)
        if stale:
            row["stale_paths"] = stale
            row["fix"] = f"schedule --name {name}"
        if last:
            job, rec = last
            state = None
            if rec.get("run_id"):
                try:
                    state = read_meta(str(Path(registry) / rec["run_id"])).get("state")
                except Refusal:
                    state = None
            row["last"] = {"job": job, "at": iso(rec.get("at")), "slot": iso(rec.get("slot")), "run_id": rec.get("run_id"), "state": state, "outcome": (rec.get("outcome") or {}).get("kind"), "url": rec.get("url")}
        out.append(row)
    prefix = dispatcher_label(repo, "")
    orphans = [{"label": l, "plist": str(Path(os.path.expanduser("~")) / "Library" / "LaunchAgents" / f"{l}.plist")} for l in list_agents(prefix) if l[len(prefix):] not in names]
    return {"repo": repo, "schedules": out, "orphans": orphans}
