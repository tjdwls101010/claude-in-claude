"""A repository's self-hosted runner as installed on this Mac, and what would keep it from running a scheduled worker (K29). GitHub's runner installs itself as a LaunchAgent `actions.runner.<owner>-<repo>.<runner>` whose plist names the runner's directory; there `.path` holds the PATH every job gets (fixed when `config.sh` ran — a PATH in `.env` does not reach jobs, stage 0 b) and `.env` other variables. A service in its own security session (`SessionCreate`, what `svc.sh install` writes) cannot read the Claude login in the Keychain (probe 9); a `CLAUDE_CODE_OAUTH_TOKEN` in `.env` works there instead (stage 0 a)."""

from __future__ import annotations

import os
import plistlib
import shutil
from pathlib import Path

TOOLS = ("uv", "claude", "gh")
TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"


def _agents():
    return Path(os.path.expanduser("~")) / "Library" / "LaunchAgents"


def _read_env(path):
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip():
                out[key.strip()] = value
    except OSError:
        pass
    return out


def local_runners(repo):
    """The runner services for `repo` installed on this Mac: `[{name, plist, dir, session_create, env_token, path_has}]` — `env_token` whether `.env` sets CLAUDE_CODE_OAUTH_TOKEN (never its value), `path_has` which of uv, claude and gh the jobs' PATH finds."""
    owner, name = repo.split("/", 1)
    prefix = f"actions.runner.{owner}-{name}."
    out = []
    d = _agents()
    for plist in sorted(d.glob(prefix + "*.plist")) if d.is_dir() else []:
        try:
            data = plistlib.loads(plist.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            data = {}
        rdir = data.get("WorkingDirectory")
        try:
            path = Path(rdir, ".path").read_text(encoding="utf-8", errors="replace").strip() if rdir else ""
        except OSError:
            path = ""
        out.append({
            "name": plist.stem[len(prefix):],
            "plist": str(plist),
            "dir": rdir,
            "session_create": bool(data.get("SessionCreate")),
            "env_token": bool(_read_env(Path(rdir, ".env")).get(TOKEN)) if rdir else False,
            "path_has": {t: bool(shutil.which(t, path=path)) for t in TOOLS} if path else {t: False for t in TOOLS},
        })
    return out


def runner_problems(registered, local, tools=("uv", "claude"), runs_on=("self-hosted",)):
    """What keeps scheduled workers from running, as `[{problem, why, fixes}]` — `none`, `offline`, `not_local`, `session_create`, `path_missing` — from the runners GitHub lists for the repository (`registered`), the services on this Mac (`local`), the `tools` jobs need on their PATH (gh too for a one-off, whose Finish step disables its workflow) and the labels a job asks for (`runs_on`). Only this Mac's services of runners with every label count: the workflow names paths on this Mac. Where there is more than one way to fix it, every way is given: which one is the Mac's owner's choice."""
    problems = []
    wanted = {l.casefold() for l in runs_on}  # GitHub matches runner labels whatever their case
    fitting = [r for r in registered if wanted <= {l.casefold() for l in r.get("labels") or []}]
    if registered and not fitting:
        problems.append({"problem": "none", "why": f"no runner of this repository has every label {', '.join(sorted(wanted))}: a scheduled job waits in GitHub's queue and fails after 24 hours", "fixes": ["Give this Mac's runner the missing labels (the repository's Settings → Actions → Runners), or schedule with --runs-on labels it has."]})
        return problems
    registered = fitting
    if not registered:
        problems.append({"problem": "none", "why": "no self-hosted runner is registered for this repository: a scheduled job waits in GitHub's queue and fails after 24 hours", "fixes": ["In the repository's Settings → Actions → Runners → New self-hosted runner (macOS), download and configure a runner on this Mac, then install it as a service from its directory with `./svc.sh install` and `./svc.sh start` (no sudo: it becomes a LaunchAgent of your login). On a personal account a runner serves one repository."]})
        return problems
    status = {r["name"]: r.get("status") for r in registered}
    mine = [l for l in local if l["name"] in status]
    if not mine:
        problems.append({"problem": "not_local", "why": "no service of this repository's runner is installed on this Mac: the workflow names paths on this Mac, so a job another machine picks up fails", "fixes": ["Install the runner as a service on this Mac (`./svc.sh install` in its directory), or remove runners on other machines from this repository."]})
        return problems
    if not any(status[l["name"]] == "online" for l in mine):
        names = ", ".join(l["name"] for l in mine)
        problems.append({"problem": "offline", "why": f"this Mac's runner ({names}) is offline: jobs wait for it up to 24 hours, then fail", "fixes": [f"Start its service from the runner's directory: `./svc.sh start` in {mine[0]['dir']}; if it was never installed as a service, `./svc.sh install` first."]})
    for l in mine:
        if l["session_create"] and not l["env_token"]:
            problems.append({"problem": "session_create", "runner": l["name"], "why": "the runner's service runs in a security session of its own (SessionCreate in its plist), which cannot read the Claude login in the Keychain: scheduled runs fail with 'Not logged in'", "fixes": [
                f"Delete SessionCreate from {l['plist']} (`/usr/libexec/PlistBuddy -c 'Delete :SessionCreate' '{l['plist']}'`) and restart the service (`./svc.sh stop && ./svc.sh start` in {l['dir']}). No secret goes on disk; every job of that runner then runs with your login session's access, and `./svc.sh install` writes the key back.",
                f"Or run `claude setup-token` and put the token in {l['dir']}/.env as {TOKEN}=… , then restart the service. The plist stays as it is; the token is plain text on disk and expires after a year.",
            ]})
        missing = [t for t in tools if not l["path_has"].get(t)]
        if missing:
            problems.append({"problem": "path_missing", "runner": l["name"], "why": f"jobs get the PATH saved in {l['dir']}/.path when the runner was configured, and it does not find {', '.join(missing)}", "fixes": [f"Add the directories of {', '.join(missing)} to {l['dir']}/.path and restart the service; a PATH set in .env does not reach jobs."]})
    return problems
