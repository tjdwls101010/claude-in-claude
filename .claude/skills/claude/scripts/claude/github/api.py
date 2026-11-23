"""GitHub through the `gh` CLI: its login and token scopes, which repository a git remote names, a repository's facts, workflow files read, committed and deleted on the default branch through the Contents API (probe 11, 15), the whole workflow directory in one GraphQL call, a workflow's state, enabling and disabling it, the repository's runners, and whether a commit is the head of a pull request merged into a branch. Every path, field and error text of GitHub's lives here; callers get the skill's own terms and GitHubError."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from urllib.parse import quote

from .job import scrub_job_env

WORKFLOWS = ".github/workflows"
REMOTE = re.compile(r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?$")


class GitHubError(Exception):
    """A gh call GitHub refused. `status` is the HTTP status (None when gh failed otherwise). `conflict` says another write changed the file first: a stale `sha` (409 "is at … but expected …" or "… does not match …", what the loser of two first creates got — stage 0 f) or a missing one (422 "sha wasn't supplied"). A protected branch also answers 409 ("Changes must be made through a pull request", captured), and is not a conflict."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.conflict = (status == 409 and (" but expected " in message or " does not match " in message)) or (status == 422 and "\"sha\" wasn't supplied" in message)


def gh_path():
    return shutil.which("gh")


def _contents(repo, file):
    """The Contents API path of a workflow file. gh reads the argument as a URL — `#` starts a fragment, `?` a query, `%` an escape (a raw `a#b.yml` wrote the file `a`) — so a name goes in percent-encoded, as does a branch in `?ref=`."""
    return f"repos/{repo}/contents/{WORKFLOWS}/{quote(file, safe='')}"


def _workflow(repo, file):
    return f"repos/{repo}/actions/workflows/{quote(file, safe='')}"


def _gh(*args, stdin=None, env=None):
    path = gh_path()
    if not path:
        raise GitHubError("gh is not on PATH")
    try:
        proc = subprocess.run([path, *args], input=stdin, capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitHubError(f"gh {args[0]} failed: {e}")
    return proc


def _api(path, method="GET", body=None, empty_ok=False, env=None):
    args = ["api", "-X", method, path]
    if body is not None:
        args += ["--input", "-"]
    proc = _gh(*args, stdin=json.dumps(body) if body is not None else None, env=env)
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


def _graphql(query, variables):
    """The `data` of a GraphQL answer; GitHubError for one that carries `errors` (status 404 when GitHub cannot resolve what was named) or is no answer."""
    proc = _gh("api", "graphql", "--input", "-", stdin=json.dumps({"query": query, "variables": variables}))
    try:
        reply = json.loads(proc.stdout)
    except ValueError:
        reply = None
    errors = reply.get("errors") if isinstance(reply, dict) else None
    if proc.returncode != 0 or errors or not isinstance(reply, dict) or not isinstance(reply.get("data"), dict):
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        raise GitHubError(first.get("message") or (proc.stderr or proc.stdout).strip() or "gh api graphql answered nothing", 404 if first.get("type") == "NOT_FOUND" else None)
    return reply["data"]


def read_workflow(repo, file, branch):
    """What sits at the workflow file's path on `branch`, as `{text, sha, url}`, or None when nothing does. `text` is None when it is not a file: the Contents API answers a directory with a list."""
    try:
        data = _api(f"{_contents(repo, file)}?ref={quote(branch, safe='')}")
    except GitHubError as e:
        if e.status == 404:
            return None
        raise
    if not isinstance(data, dict):
        return {"text": None, "sha": None, "url": None}
    # A file that is not UTF-8 is nobody's schedule; it is read without failing.
    text = base64.b64decode(data.get("content") or "").decode("utf-8", "replace")
    return {"text": text, "sha": data.get("sha"), "url": data.get("html_url")}


def write_workflow(repo, file, text, message, branch, sha=None):
    """Commit the workflow file to `branch`: create it, or replace the version `sha` names. `{commit, url}`. GitHubError with `conflict` when the file changed since `sha` was read."""
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": branch}
    if sha:
        body["sha"] = sha
    data = _api(_contents(repo, file), "PUT", body)
    return {"commit": (data.get("commit") or {}).get("sha"), "url": (data.get("content") or {}).get("html_url")}


def delete_workflow(repo, file, message, branch, sha):
    """Delete the workflow file from `branch`; `{commit}`."""
    data = _api(_contents(repo, file), "DELETE", {"message": message, "branch": branch, "sha": sha})
    return {"commit": (data.get("commit") or {}).get("sha")}


def workflow_state(repo, file):
    """`active`, `disabled_manually`, … as GitHub reports it, or None when GitHub knows no such workflow."""
    try:
        return _api(_workflow(repo, file)).get("state")
    except GitHubError as e:
        if e.status == 404:
            return None
        raise


def set_workflow_enabled(repo, file, enabled):
    _api(f"{_workflow(repo, file)}/{'enable' if enabled else 'disable'}", "PUT", empty_ok=True)


WORKFLOW_FILES = "query($owner: String!, $name: String!, $e: String!) { repository(owner: $owner, name: $name) { object(expression: $e) { ... on Tree { entries { name type object { ... on Blob { byteSize isTruncated text } } } } } } }"


def list_workflow_files(repo, branch):
    """Everything in the workflow directory on `branch`, in one GraphQL call: `[{file, kind, text}]`, `kind` as git names it (`blob`, `tree`, …) and `text` the body of a `.yml` or `.yaml` blob, None for anything else. A body the call did not bring whole (GraphQL gives none for a binary blob and marks a cut one) is read on its own. An empty list when the directory is not there."""
    owner, name = repo.split("/", 1)
    repository = _graphql(WORKFLOW_FILES, {"owner": owner, "name": name, "e": f"{branch}:{WORKFLOWS}"}).get("repository")
    if repository is None:
        raise GitHubError(f"GitHub does not show {repo}", 404)
    out = []
    for entry in (repository.get("object") or {}).get("entries") or []:
        file, kind, blob = entry.get("name"), entry.get("type"), entry.get("object") or {}
        text = None
        if kind == "blob" and file.lower().endswith((".yml", ".yaml")):
            text = None if blob.get("isTruncated") else blob.get("text")
            if text is None:
                text = (read_workflow(repo, file, branch) or {}).get("text")
        out.append({"file": file, "kind": kind, "text": text})
    return out


def workflow_states(repo):
    """The state of every workflow GitHub has registered from the workflow directory: `{file: state}`. A file committed a moment ago can be missing."""
    out, page = {}, 1
    while True:
        batch = _api(f"repos/{repo}/actions/workflows?per_page=100&page={page}").get("workflows") or []
        for w in batch:
            path = w.get("path") or ""
            if path.startswith(WORKFLOWS + "/"):
                out[path[len(WORKFLOWS) + 1 :]] = w.get("state")
        if len(batch) < 100:
            return out
        page += 1


def runners(repo):
    """The repository's self-hosted runners: `[{name, status, busy, labels}]` (`status` is `online` or `offline`)."""
    data = _api(f"repos/{repo}/actions/runners")
    return [{"name": r.get("name"), "status": r.get("status"), "busy": bool(r.get("busy")), "labels": [l.get("name") for l in r.get("labels") or []]} for r in data.get("runners") or []]


def pull_evidence(repo, sha, branch):
    """What GitHub says of commit `sha` in `repo` (the person's login, not a job's token, which may not read pull requests): `{kind: merged, number, url}` when a pull request whose head is exactly that commit was merged into `branch` of `repo` — a squash or rebase merge leaves other commits on the branch, so git alone cannot tell; `open` (same, not yet merged); `other` when its pull requests go elsewhere or were closed unmerged; `none` when no pull request has it as its head or GitHub does not have the commit; `unknown` (with `error`) when GitHub could not be asked."""
    try:
        # 성진: one page of 100; a commit at the head of more pull requests than that is not looked past.
        pulls = _api(f"repos/{repo}/commits/{sha}/pulls?per_page=100", env=scrub_job_env(os.environ))
    except GitHubError as e:
        if e.status == 422 and "No commit found" in e.message:
            return {"kind": "none"}
        return {"kind": "unknown", "error": e.message}
    found = {}
    for pr in pulls if isinstance(pulls, list) else []:
        if (pr.get("head") or {}).get("sha") != sha:
            continue
        base = pr.get("base") or {}
        here = base.get("ref") == branch and ((base.get("repo") or {}).get("full_name") or "").lower() == repo.lower()
        kind = "merged" if here and pr.get("merged_at") else "open" if here and pr.get("state") == "open" else "other"
        found.setdefault(kind, {"kind": kind, "number": pr.get("number"), "url": pr.get("html_url")})
    for kind in ("merged", "open"):
        if kind in found:
            return found[kind]
    return {"kind": "other"} if found else {"kind": "none"}
