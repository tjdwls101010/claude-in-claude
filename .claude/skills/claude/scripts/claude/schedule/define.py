"""`schedule`, `unschedule` and `schedule --list`: a schedule is a workflow file committed to the repository's default branch through the GitHub API, which is its definition and GitHub's backup cron, plus a LaunchAgent on this Mac that starts it on time (K12). The two writes go to two systems, so each reply says how each went rather than hiding half of a failure; both happen under the schedule's lock, as does a one-off's Finish deciding to disable it (K8)."""

from __future__ import annotations

import os
from pathlib import Path

from claude.errors import Refusal
from claude.git import main_checkout, remote_url, toplevel
from claude.github import GitHubError, delete_workflow, gh_status, list_workflow_files, local_runners, parse_spec, read_workflow, render_workflow, repo_facts, repo_from_remote, runner_problems, runners, set_workflow_enabled, workflow_file, workflow_state, workflow_states, write_workflow
from claude.launchd import agent_state, agents_dir, calendar_entries, install_agent, list_agents, remove_agent, render_agent, supported, system_timezone
from claude.registry import latest_job, read_meta, remove_schedule_state, resolve_runs_dir, schedule_dir, schedule_lock, schedule_runs_live, schedule_state_holder, write_definition
from claude.runs import refuse_inside_worker
from claude.util import entry_path, iso

from .execute import clock, local_time
from .spec import check_name, dispatcher_holder, dispatcher_label, fields_of, merge
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
    if spec is None or spec.get("name") != file[len(PREFIX):-len(".yml")]:
        raise Refusal(f".github/workflows/{file} exists and was not written by this skill; choose another --name")
    return current, spec


def _runner(repo, tools, runs_on):
    try:
        registered = runners(repo)
    except GitHubError as e:
        return {"registered": None, "local": local_runners(repo), "problems": [], "error": f"the runners could not be listed: {e.message}"}
    local = local_runners(repo)
    return {"registered": registered, "local": local, "problems": runner_problems(registered, local, tools, runs_on)}


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
    # GitHub's spelling of the repository, as GITHUB_REPOSITORY gives it to the job: the dispatcher's label must be the one a one-off's Finish removes.
    repo = facts["full_name"] or repo
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

    def refuse_held():
        """This Mac's dispatcher plist path and state directory must be free or this schedule's own, or installing and recording would overwrite another schedule's."""
        held = dispatcher_holder(repo, name)
        if held:
            raise Refusal(f"the dispatcher of {name} would go where this Mac keeps {held}", instead="choose another --name; if that plist is a leftover, delete it and schedule again")
        held = schedule_state_holder(registry, name)
        if held:
            raise Refusal(f"the state of {name} would go where this Mac keeps the state of schedule {held} ({schedule_dir(registry, name)})", instead="choose another --name")

    def refusals_first():
        """The refusals that need only what GitHub and this Mac already hold, checked before the lock — which creates the registry — so a refusal writes nothing on this Mac."""
        current, recorded = _existing(repo, file, branch)
        refuse_held()
        return build(current, recorded)

    def derived(spec):
        """Everything that follows from the spec finally committed: the dispatcher's calendar and command, the runner check, the reply's settings."""
        return calendar_entries(fields_of(spec)), dispatcher_argv(gh["path"], repo, file, branch), _runner(repo, ("uv", "claude", "gh") if spec.get("at") else ("uv", "claude"), spec["runs_on"]), {k: spec[k] for k in ("profile", "model", "effort", "timeout", "worktree", "runs_on")}

    if dry_run:
        spec, text = refusals_first()
        calendar, argv, runner, settings = derived(spec)
        return {"name": name, "repo": repo, "dry_run": True, "workflow_path": f".github/workflows/{file}", "workflow_text": text, "dispatcher_label": label, "dispatcher_text": render_agent(label, argv, calendar, log), "fires": _fires(spec, now), "settings": settings, "runner": runner}

    warnings = []
    refusals_first()
    # Read, merge, commit and install under the lock, so a second call on this Mac sees what the first committed (K8, K12); the clock is read again inside, since waiting for the lock can take a one-off's time past.
    with schedule_lock(registry, name):
        now = clock()
        current, recorded = _existing(repo, file, branch)
        refuse_held()
        spec, text = build(current, recorded)
        status = "unchanged"
        commit = url = None
        if current is None or current["text"] != text:
            for attempt in (1, 2):
                message_text = message or (f"Schedule Claude worker {name}: " + (f"once at {spec['at']} ({timezone})" if spec.get("at") else f"{spec['cron']} ({timezone})"))
                if spec.get("at") and not fire_times(spec, clock(), 1):
                    # A one-off's time can pass while GitHub answers; checked once more right before the write.
                    raise Refusal(f"the one-off time {spec['at']} passed while scheduling; nothing was committed", instead="schedule again with a later --at")
                try:
                    done = write_workflow(repo, file, text, message_text, branch, sha=(current or {}).get("sha"))
                    status, commit, url = "committed", done["commit"], done["url"]
                    break
                except GitHubError as e:
                    if not e.conflict or attempt == 2:
                        if e.status is None:
                            # GitHub may hold the new definition now: no job started from the old one may match this Mac's record any more (K8).
                            write_definition(registry, name, None)
                            raise Refusal(f"the commit to {branch} got no answer from GitHub: {e.message}", instead="whether GitHub committed it is unknown; run the same command again once gh reaches GitHub (with a later --at if a one-off's time has passed) — it finds the workflow committed or not, and installs the dispatcher")
                        raise Refusal(f"GitHub refused the commit to {branch} (HTTP {e.status}): {e.message}", instead="`schedule … --dry-run` prints the workflow file; commit it through a pull request, then call `schedule` again to install the dispatcher")
                    # Another call committed first: merge onto what it committed and try once more (K12).
                    current, recorded = _existing(repo, file, branch)
                    spec, text = build(current, recorded)
                    if current is not None and current["text"] == text:
                        break
        calendar, argv, runner, settings = derived(spec)
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
    if spec.get("at") and not fire_times(spec, clock(), 1):
        warnings.append(f"the one-off time {spec['at']} passed while scheduling, so neither the dispatcher nor GitHub will start it until next year, when it is skipped; `schedule --name {name} --at <later>` sets a new time")
    elif spec.get("at"):
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
    repo = facts["full_name"] or repo
    branch = facts["default_branch"]
    file = workflow_file(name)
    registry = resolve_runs_dir(project)
    reply = {"name": name, "repo": repo}
    with schedule_lock(registry, name):
        try:
            current = read_workflow(repo, file, branch)
        except GitHubError as e:
            current, reply["workflow"] = None, {"status": "failed", "path": f".github/workflows/{file}", "error": e.message}
        if current is not None and (parse_spec_or_none(current["text"]) or {}).get("name") != name:
            raise Refusal(f".github/workflows/{file} was not written by this skill; unschedule leaves it alone")
        label = dispatcher_label(repo, name)
        plist_held, state_held = dispatcher_holder(repo, name), schedule_state_holder(registry, name)
        if current is None and "workflow" not in reply and (plist_held or state_held):
            raise Refusal(f"{repo} has no schedule {name}, and what this Mac keeps under that name is another schedule's: " + (plist_held or f"the state of schedule {state_held} ({schedule_dir(registry, name)})") + "; nothing was removed")
        notes = []
        if plist_held:
            # The path holds another schedule's plist: this schedule has no dispatcher on this Mac.
            reply["dispatcher"] = {"status": "absent", "label": label, "plist": str(agents_dir() / f"{label}.plist")}
            notes.append(f"the dispatcher plist path holds {plist_held}, which was left alone")
        else:
            reply["dispatcher"] = remove_agent(label)
        if "workflow" not in reply:
            if current is None:
                reply["workflow"] = {"status": "absent", "path": f".github/workflows/{file}"}
            else:
                try:
                    done = delete_workflow(repo, file, message or f"Unschedule Claude worker {name}", branch, current["sha"])
                    reply["workflow"] = {"status": "deleted", "path": f".github/workflows/{file}", "commit": done["commit"]}
                except GitHubError as e:
                    reply["workflow"] = {"status": "failed", "path": f".github/workflows/{file}", "error": e.message}
        live = schedule_runs_live(registry, name)
        if state_held:
            notes.append(f"the state directory under that name is schedule {state_held}'s and was left alone")
        elif live:
            # The live run's Finish still needs its job's hand-over; only the definition goes, so it will not disable anything (K8).
            write_definition(registry, name, None)
            notes.append(f"run(s) {', '.join(live)} of this schedule are still live, so its local state is kept until they end; `gh run cancel <id> --repo {repo}` cancels a job")
        else:
            remove_schedule_state(registry, name)
        if notes:
            reply["note"] = "; ".join(notes)
    return reply


def parse_spec_or_none(text):
    try:
        return parse_spec(text)
    except ValueError:
        return None


def schedules(*, cwd):
    """The repository's schedules (see `schedule --list`)."""
    refuse_inside_worker()
    _gh_ready(need_workflow_scope=False)
    project, repo = _project(cwd)
    facts = _facts(repo)
    repo = facts["full_name"] or repo
    registry = resolve_runs_dir(project)
    out, names = [], set()
    try:
        # A schedule is a file that starts with the skill's header and carries its spec line, whatever it is called.
        files = list_workflow_files(repo, facts["default_branch"])
        states = workflow_states(repo)
    except GitHubError as e:
        raise Refusal(f"the workflows could not be listed: {e.message}")
    found = []
    for f in files:
        spec = parse_spec_or_none(f["text"])
        if spec:
            found.append((spec["name"], f["file"], spec))
    for name, file, spec in sorted(found, key=lambda x: x[:2]):
        names.add(name)
        last = latest_job(registry, name)
        state = states.get(file)
        row = {"name": name, "file": file, "cron": spec.get("cron"), "at": spec.get("at"), "timezone": spec.get("timezone"), "profile": spec.get("profile"), "state": "unknown" if state is None else "active" if state == "active" else "disabled", "dispatcher": "loaded" if agent_state(dispatcher_label(repo, name)) == "loaded" else "missing"}
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
    # Only plists that are this repository's own: the prefix also matches another repository's labels, and a path can hold another label's plist.
    orphans = [{"label": l, "plist": str(agents_dir() / f"{l}.plist")} for l in list_agents(prefix) if l[len(prefix):] not in names and dispatcher_holder(repo, l[len(prefix):]) is None]
    return {"repo": repo, "schedules": out, "orphans": orphans}
