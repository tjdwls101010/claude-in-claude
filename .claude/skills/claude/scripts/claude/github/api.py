"""GitHub through the `gh` CLI: its login and token scopes, which repository a git remote names, a repository's facts, workflow files read, committed and deleted on the default branch through the Contents API (probe 11, 15), a workflow's state, enabling and disabling it, and the repository's runners. Every path, field and error text of GitHub's lives here; callers get the skill's own terms and GitHubError."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess

WORKFLOWS = ".github/workflows"
REMOTE = re.compile(r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$")


class GitHubError(Exception):
    """A gh call GitHub refused. `status` is the HTTP status (None when gh failed otherwise); `conflict` says another write changed the file first — a stale or missing `sha` (HTTP 409, or 422 "sha wasn't supplied", which is what the loser of two first creates can get)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.conflict = status == 409 or (status == 422 and "\"sha\" wasn't supplied" in message)


def gh_path():
    return shutil.which("gh")


def _gh(*args, stdin=None, env=None):
    path = gh_path()
    if not path:
        raise GitHubError("gh is not on PATH")
    try:
        proc = subprocess.run([path, *args], input=stdin, capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitHubError(f"gh {args[0]} failed: {e}")
    return proc


def _api(path, method="GET", body=None, empty_ok=False):
    args = ["api", "-X", method, path]
    if body is not None:
        args += ["--input", "-"]
    proc = _gh(*args, stdin=json.dumps(body) if body is not None else None)
    if proc.returncode != 0:
        status = None
        message = (proc.stderr or proc.stdout).strip()
        try:
            data = json.loads(proc.stdout)
            message = data.get("message") or message
            status = int(data["status"]) if str(data.get("status", "")).isdigit() else None
        except (ValueError, AttributeError):
            pass
        if status is None:
            m = re.search(r"\(HTTP (\d{3})\)", proc.stderr or "")
            status = int(m.group(1)) if m else None
        raise GitHubError(message.replace("\n\n", " ").strip(), status)
    if not proc.stdout.strip():
        if empty_ok:
            return None
        raise GitHubError(f"gh api {path} answered nothing")
    return json.loads(proc.stdout)


def gh_status():
    """`{path, logged_in, login, scopes, error}` of the gh on PATH for github.com."""
    path = gh_path()
    if not path:
        return {"path": None, "logged_in": False, "login": None, "scopes": [], "error": "gh is not on PATH"}
    proc = _gh("auth", "status", "--active", "--hostname", "github.com", "--json", "hosts")
    try:
        hosts = (json.loads(proc.stdout).get("hosts") or {}).get("github.com") or []
    except ValueError:
        return {"path": path, "logged_in": False, "login": None, "scopes": [], "error": f"gh auth status did not answer in JSON: {(proc.stderr or proc.stdout).strip()[:200]}"}
    active = next((h for h in hosts if h.get("active")), hosts[0] if hosts else None)
    if not active or active.get("state") != "success":
        return {"path": path, "logged_in": False, "login": (active or {}).get("login"), "scopes": [], "error": "gh is not logged in to github.com; run `gh auth login`"}
    scopes = [s.strip() for s in (active.get("scopes") or "").split(",") if s.strip()]
    return {"path": path, "logged_in": True, "login": active.get("login"), "scopes": scopes, "error": None}


def repo_from_remote(url):
    """`owner/name` of a github.com remote URL (https, ssh or scp form), or None."""
    m = REMOTE.match((url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def repo_facts(repo):
    """`{full_name, private, default_branch, can_push}`; GitHubError (status 404) when gh cannot see it."""
    data = _api(f"repos/{repo}")
    return {"full_name": data.get("full_name"), "private": bool(data.get("private")), "default_branch": data.get("default_branch"), "can_push": bool((data.get("permissions") or {}).get("push"))}


def read_workflow(repo, file, branch):
    """The workflow file on `branch` as `{text, sha, url}`, or None when there is none."""
    try:
        data = _api(f"repos/{repo}/contents/{WORKFLOWS}/{file}?ref={branch}")
    except GitHubError as e:
        if e.status == 404:
            return None
        raise
    text = base64.b64decode(data.get("content") or "").decode("utf-8")
    return {"text": text, "sha": data.get("sha"), "url": data.get("html_url")}


def write_workflow(repo, file, text, message, branch, sha=None):
    """Commit the workflow file to `branch`: create it, or replace the version `sha` names. `{commit, url}`. GitHubError with `conflict` when the file changed since `sha` was read."""
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": branch}
    if sha:
        body["sha"] = sha
    data = _api(f"repos/{repo}/contents/{WORKFLOWS}/{file}", "PUT", body)
    return {"commit": (data.get("commit") or {}).get("sha"), "url": (data.get("content") or {}).get("html_url")}


def delete_workflow(repo, file, message, branch, sha):
    """Delete the workflow file from `branch`; `{commit}`."""
    data = _api(f"repos/{repo}/contents/{WORKFLOWS}/{file}", "DELETE", {"message": message, "branch": branch, "sha": sha})
    return {"commit": (data.get("commit") or {}).get("sha")}


def workflow_state(repo, file):
    """`active`, `disabled_manually`, … as GitHub reports it, or None when GitHub knows no such workflow."""
    try:
        return _api(f"repos/{repo}/actions/workflows/{file}").get("state")
    except GitHubError as e:
        if e.status == 404:
            return None
        raise


def set_workflow_enabled(repo, file, enabled):
    _api(f"repos/{repo}/actions/workflows/{file}/{'enable' if enabled else 'disable'}", "PUT", empty_ok=True)


def list_workflows(repo, prefix):
    """The repository's workflows whose file name starts with `prefix`: `[{file, state}]`."""
    data = _api(f"repos/{repo}/actions/workflows?per_page=100")
    out = []
    for w in data.get("workflows") or []:
        file = (w.get("path") or "").rsplit("/", 1)[-1]
        if (w.get("path") or "").startswith(WORKFLOWS + "/") and file.startswith(prefix):
            out.append({"file": file, "state": w.get("state")})
    return out


def runners(repo):
    """The repository's self-hosted runners: `[{name, status, busy, labels}]` (`status` is `online` or `offline`)."""
    data = _api(f"repos/{repo}/actions/runners")
    return [{"name": r.get("name"), "status": r.get("status"), "busy": bool(r.get("busy")), "labels": [l.get("name") for l in r.get("labels") or []]} for r in data.get("runners") or []]
