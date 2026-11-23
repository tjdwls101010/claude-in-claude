"""Bringing a checkout's default branch up to what its `origin` holds, the way a person would with `git pull --ff-only`, but never over anything of theirs: git itself refuses a fast-forward that would touch a changed file, an untracked or ignored one, a branch checked out elsewhere or one with commits of its own, and this module reports each refusal in words instead of working around it (no stash, reset, rebase or force)."""

from __future__ import annotations

import os
import shlex

from .repo import current_branch, head_commit, run_git, toplevel

NETWORK_SECONDS = 120
MERGE_SECONDS = 60
COMMITS_SHOWN = 20
FILES_SHOWN = 20
# Nothing a person would be asked for: no terminal prompt, no askpass program, and ssh in batch mode. A credential helper (such as gh's) still answers.
QUIET = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": ""}
# The repository's hooks are the person's: an unattended update does not run them with whatever environment it has.
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")
# Files in the git directory that mean an operation is half done; a fast-forward then would land in the middle of it.
IN_PROGRESS = (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase or `git am`"), ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert"), ("BISECT_LOG", "a bisect"))
OVERWRITE = {
    "Your local changes to the following files would be overwritten": "changed",
    "untracked working tree files would be overwritten": "untracked",
}


def _env(base):
    env = dict(os.environ if base is None else base)
    env.update(QUIET)
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def _last_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip() and not l.startswith("hint:")]
    return lines[-1] if lines else "no message"


def git_busy(path, env=None):
    """What half-done git operation the checkout at `path` is in — a merge, rebase, cherry-pick, revert or bisect, or an index with unmerged paths — in words, or None."""
    for name, what in IN_PROGRESS:
        code, out, _ = run_git(path, "rev-parse", "--git-path", name, env=env)
        target = out.strip()
        if code == 0 and target and os.path.exists(target if os.path.isabs(target) else os.path.join(path, target)):
            return what
    code, out, _ = run_git(path, "ls-files", "--unmerged", env=env)
    if code == 0 and out.strip():
        return "a merge with unresolved conflicts"
    return None


def _default_branch(top, env):
    """(branch, None) for origin's HEAD as origin says it now, or (None, why)."""
    code, out, err = run_git(top, "ls-remote", "--symref", "origin", "HEAD", env=env, timeout=NETWORK_SECONDS)
    if code != 0:
        return None, f"origin could not be read: {_last_line(err)}"
    for line in out.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line[len("ref: refs/heads/"):-len("\tHEAD")], None
    return None, "origin does not name a default branch"


def _rev(top, ref, env):
    code, out, _ = run_git(top, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", env=env)
    return out.strip() if code == 0 and out.strip() else None


def _is_ancestor(top, older, newer, env):
    code, _, _ = run_git(top, "merge-base", "--is-ancestor", older, newer, env=env)
    return code == 0


def _count(top, spec, env):
    code, out, _ = run_git(top, "rev-list", "--count", spec, env=env)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else 0


def _commits(top, old, new, env):
    """([{sha7, subject}] from `old` to `new`, newest first, at most COMMITS_SHOWN; how many more there are)."""
    code, out, _ = run_git(top, "log", f"--max-count={COMMITS_SHOWN}", "--format=%h%x00%s", f"{old}..{new}", env=env)
    shown = []
    for line in out.splitlines() if code == 0 else []:
        sha, _, subject = line.partition("\0")
        shown.append({"sha7": sha, "subject": subject})
    return shown, max(0, _count(top, f"{old}..{new}", env) - len(shown))


def _overwritten(err):
    """(kind, [paths]) when git refused because the update would overwrite files in the work tree, else None."""
    lines = (err or "").splitlines()
    for i, line in enumerate(lines):
        for marker, kind in OVERWRITE.items():
            if marker in line:
                files = []
                for following in lines[i + 1:]:
                    if not following.startswith(("\t", "    ")):
                        break
                    files.append(following.strip())
                return kind, files
    return None


def _ahead_reason(top, local, remote, branch, env):
    mine = _count(top, f"{remote}..{local}", env)
    theirs = _count(top, f"{local}..{remote}", env)
    if theirs:
        return f"local {branch} and origin's have gone apart: {mine} commit{'s' if mine != 1 else ''} here that origin does not have, {theirs} on origin"
    return f"local {branch} has {mine} commit{'s' if mine != 1 else ''} origin does not have"


def branch_contains(path, branch, commit, env=None):
    """Whether the local `branch` of the repository at `path` holds `commit` (False when either is unknown here)."""
    if not branch or not commit:
        return False
    code, _, _ = run_git(path, "merge-base", "--is-ancestor", commit, f"refs/heads/{branch}", env=env)
    return code == 0


def sync_default(checkout, *, fetch_only=False, env=None):
    """Bring the default branch of the checkout at `checkout` up to origin's, as far as that changes nothing of the person's. Never raises.

    The branch is the one origin's HEAD names now; it is fetched by its full name and the commit fetched is the one everything below compares and moves to. When it is the branch checked out here, the work tree is fast-forwarded (no hooks, ignored files not overwritten); otherwise only the local branch moves, as `git fetch` would move it, and files stay as they are. `fetch_only` stops after the fetch.

    Returns `{status, path, branch, files_updated, from, to, commits, more, reason, files, instead}`: `status` is `updated` (work tree too), `ref_updated` (the branch only), `current` (local and origin are one commit), `fetched` (`fetch_only`), `not_updated` (left alone because updating would touch something of the person's — `reason` says what, `files` which, `instead` what to run once it is sorted) or `failed` (git or the network failed — `reason`). `commits` lists what came in, newest first, `more` how many it leaves out."""
    env = _env(env)
    out = {"status": None, "path": None, "branch": None, "files_updated": False, "from": None, "to": None, "commits": [], "more": 0, "reason": None, "files": [], "instead": None}
    top = toplevel(checkout)
    if top is None:
        return {**out, "status": "failed", "path": str(checkout), "reason": f"{checkout} is not a git checkout"}
    out["path"] = top
    q = shlex.quote(top)
    branch, why = _default_branch(top, env)
    if branch is None:
        return {**out, "status": "failed", "reason": why}
    out["branch"] = branch
    tracking = f"refs/remotes/origin/{branch}"
    code, _, err = run_git(top, *NO_HOOKS, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "origin", f"+refs/heads/{branch}:{tracking}", env=env, timeout=NETWORK_SECONDS)
    remote = _rev(top, tracking, env) if code == 0 else None
    if remote is None:
        return {**out, "status": "failed", "reason": f"fetching {branch} from origin failed: {_last_line(err)}"}
    out["to"] = remote
    if fetch_only:
        return {**out, "status": "fetched"}
    busy = git_busy(top, env)
    if busy:
        return {**out, "status": "not_updated", "reason": f"the checkout is in the middle of {busy}", "instead": f"finish or abort it (`git -C {q} status` says how), then `git -C {q} merge --ff-only origin/{branch}`"}
    here = current_branch(top) == branch
    local = head_commit(top) if here else _rev(top, f"refs/heads/{branch}", env)
    if local is None:
        return {**out, "status": "not_updated", "reason": f"there is no local branch {branch}", "instead": f"`git -C {q} branch {shlex.quote(branch)} origin/{branch}` makes it"}
    out["from"] = local
    if local == remote:
        return {**out, "status": "current"}
    if not _is_ancestor(top, local, remote, env):
        return {**out, "status": "not_updated", "reason": _ahead_reason(top, local, remote, branch, env), "instead": f"`git -C {q} log origin/{branch}...{shlex.quote(branch)}` shows both sides; push, rebase or merge them yourself"}
    if here:
        code, _, err = run_git(top, *NO_HOOKS, "merge", "--ff-only", "--no-overwrite-ignore", "--no-edit", remote, env=env, timeout=MERGE_SECONDS)
        if code != 0:
            hit = _overwritten(err)
            if hit is None:
                return {**out, "status": "failed", "reason": f"the fast-forward failed: {_last_line(err)}", "instead": f"`git -C {q} merge --ff-only origin/{branch}`"}
            kind, files = hit
            n = len(files)
            what = f"you have changes to {n} file{'s' if n != 1 else ''} that the incoming commits also change" if kind == "changed" else f"{n} untracked or ignored file{'s' if n != 1 else ''} here would be overwritten by files the incoming commits add"
            return {**out, "status": "not_updated", "reason": what, "files": files[:FILES_SHOWN], "instead": f"commit, move or remove {'them' if n != 1 else 'it'}, then `git -C {q} merge --ff-only origin/{branch}`"}
        status = "updated"
    else:
        # Through git, not update-ref: it refuses a branch checked out in any worktree and anything but a fast-forward.
        code, _, err = run_git(top, *NO_HOOKS, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", ".", f"{tracking}:refs/heads/{branch}", env=env, timeout=MERGE_SECONDS)
        if code != 0:
            if "checked out at" in err or "refusing to fetch into" in err:
                return {**out, "status": "not_updated", "reason": f"{branch} is checked out in another worktree ({_last_line(err)})", "instead": f"update it there: `git merge --ff-only origin/{branch}`"}
            return {**out, "status": "failed", "reason": f"moving {branch} failed: {_last_line(err)}", "instead": f"`git -C {q} fetch origin {shlex.quote(branch)}:{shlex.quote(branch)}`"}
        status = "ref_updated"
    commits, more = _commits(top, local, remote, env)
    return {**out, "status": status, "files_updated": status == "updated", "commits": commits, "more": more}
