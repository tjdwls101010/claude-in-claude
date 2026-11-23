"""Bringing a checkout's default branch up to what its origin holds, the way a person would with `git pull --ff-only`, but never over anything of theirs: git itself refuses a fast-forward that would touch a changed file, an untracked or ignored one, a branch checked out elsewhere or one with commits of its own, and this module reports each refusal in words instead of working around it (no stash, reset, rebase or force). The person's own git settings that would change what a fast-forward does — autostash, squash, extra fetch mappings, hooks — are switched off for these commands only."""

from __future__ import annotations

import os
import shlex

from claude.util import nfc

from .repo import run_git

NETWORK_SECONDS = 120
MERGE_SECONDS = 60
COMMITS_SHOWN = 20
FILES_SHOWN = 20
# Nothing a person would be asked for: no terminal prompt, no askpass program, ssh in batch mode; a credential helper (such as gh's) still answers. Git's messages in English, which is what the refusals below are read in.
QUIET = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": "", "LC_ALL": "C"}
# The repository's hooks are the person's: an unattended update does not run them with whatever environment it has. Paths unquoted, so the files a refusal lists are the paths as they are.
SAFE = ("-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false")
# Only the ref named on the command line moves: no mapping from remote.origin.fetch (which can point at a local branch), no pruning, no tags, no FETCH_HEAD of the person's overwritten.
FETCH = ("fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-prune", "--no-write-fetch-head", "--refmap=")
# A fast-forward and nothing else, whatever merge.autostash or branch.<b>.mergeOptions say.
MERGE = ("merge", "--ff-only", "--no-overwrite-ignore", "--no-autostash", "--no-squash", "--no-edit", "--no-stat")
# Files in the git directory that mean an operation is half done; a fast-forward then would land in the middle of it.
IN_PROGRESS = (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase or `git am`"), ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert"), ("BISECT_LOG", "a bisect"))
OVERWRITE = {
    "Your local changes to the following files would be overwritten": "changed",
    "untracked working tree files would be overwritten": "untracked",
    "Updating the following directories would lose untracked files in them": "directory",
}


def _env(base):
    env = dict(os.environ if base is None else base)
    env.update(QUIET)
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def _out(path, env, *args, timeout=30):
    code, out, _ = run_git(path, *args, env=env, timeout=timeout)
    return out.strip() if code == 0 and out.strip() else None


def _last_line(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip() and not l.startswith("hint:")]
    return lines[-1] if lines else "no message"


def _rev(top, ref, env):
    return _out(top, env, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")


def _on(top, env):
    """(branch checked out or None, HEAD's commit or None)."""
    return _out(top, env, "symbolic-ref", "--short", "-q", "HEAD"), _rev(top, "HEAD", env)


def git_busy(path, env=None):
    """What half-done git operation the checkout at `path` is in — a merge, rebase, cherry-pick, revert or bisect, or an index with unmerged paths — in words, or None."""
    for name, what in IN_PROGRESS:
        target = _out(path, env, "rev-parse", "--git-path", name)
        if target and os.path.exists(target if os.path.isabs(target) else os.path.join(path, target)):
            return what
    if _out(path, env, "ls-files", "--unmerged"):
        return "a merge with unresolved conflicts"
    return None


def _default_branch(top, env):
    """(branch, None) for origin's HEAD as origin says it now, or (None, why)."""
    code, out, err = run_git(top, *SAFE, "ls-remote", "--symref", "origin", "HEAD", env=env, timeout=NETWORK_SECONDS)
    if code != 0:
        return None, f"origin could not be read: {_last_line(err)}"
    for line in out.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            return line[len("ref: refs/heads/"):-len("\tHEAD")], None
    return None, "origin does not name a default branch"


def _is_ancestor(top, older, newer, env):
    code, _, _ = run_git(top, "merge-base", "--is-ancestor", older, newer, env=env)
    return code == 0


def _count(top, spec, env):
    n = _out(top, env, "rev-list", "--count", spec)
    return int(n) if n and n.isdigit() else 0


def _commits(top, old, new, env):
    """([{sha7, subject}] from `old` to `new`, newest first, at most COMMITS_SHOWN; how many more there are)."""
    code, out, _ = run_git(top, "log", "--encoding=UTF-8", f"--max-count={COMMITS_SHOWN}", "--format=%h%x00%s", f"{old}..{new}", env=env, errors="replace")
    out = out if code == 0 else ""
    shown = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\0")
        shown.append({"sha7": sha, "subject": subject})
    return shown, max(0, _count(top, f"{old}..{new}", env) - len(shown))


def _overwritten(err):
    """(kind, [paths]) when git refused because the update would overwrite or lose files in the work tree, else None."""
    lines = (err or "").splitlines()
    for i, line in enumerate(lines):
        for marker, kind in OVERWRITE.items():
            if marker in line:
                files = []
                for following in lines[i + 1:]:
                    if not following.startswith(("\t", "    ")):
                        break
                    files.append(nfc(following[1:] if following.startswith("\t") else following[4:]))
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


def sync_default(checkout, *, fetch_only=False, env=None, guard=None):
    """Bring the default branch of the checkout at `checkout` up to origin's, as far as that changes nothing of the person's. Never raises. Every git command runs in `env` (this process's environment when None) with prompts off.

    The branch is the one origin's HEAD names now; it is fetched by its full name and the commit fetched is the one everything below compares and moves to. When it is the branch checked out here, the work tree is fast-forwarded (no hooks, ignored files not overwritten); otherwise only the local branch moves, and files stay as they are. `fetch_only` stops after the fetch. `guard`, when given, is called right before anything changes and returns a reason to leave the checkout alone, or None.

    Returns `{status, path, branch, files_updated, from, to, commits, more, reason, files, instead}`: `status` is `updated` (work tree too), `ref_updated` (the branch only), `current` (local and origin are one commit), `fetched` (`fetch_only`), `not_updated` (left alone because updating would touch something of the person's — `reason` says what, `files` which, `instead` what to run once it is sorted) or `failed` (git or the network failed, or the checkout changed under the update — `reason`). `commits` lists what came in, newest first, `more` how many it leaves out."""
    env = _env(env)
    out = {"status": None, "path": None, "branch": None, "files_updated": False, "from": None, "to": None, "commits": [], "more": 0, "reason": None, "files": [], "instead": None}
    top = _out(checkout, env, "rev-parse", "--show-toplevel")
    if top is None:
        return {**out, "status": "failed", "path": str(checkout), "reason": f"{checkout} is not a git checkout"}
    top = nfc(top)
    out["path"] = top
    q = shlex.quote(top)
    branch, why = _default_branch(top, env)
    if branch is None:
        return {**out, "status": "failed", "reason": why}
    out["branch"] = branch
    tracking = f"refs/remotes/origin/{branch}"
    ff = f"`git -C {q} merge {' '.join(MERGE[1:3])} {shlex.quote('origin/' + branch)}`"
    code, _, err = run_git(top, *SAFE, *FETCH, "origin", f"+refs/heads/{branch}:{tracking}", env=env, timeout=NETWORK_SECONDS)
    remote = _rev(top, tracking, env) if code == 0 else None
    if remote is None:
        return {**out, "status": "failed", "reason": f"fetching {branch} from origin failed: {_last_line(err)}"}
    out["to"] = remote
    if fetch_only:
        return {**out, "status": "fetched"}
    busy = git_busy(top, env)
    if busy:
        return {**out, "status": "not_updated", "reason": f"the checkout is in the middle of {busy}", "instead": f"finish or abort it (`git -C {q} status` says how), then {ff}"}
    on, head = _on(top, env)
    here = on == branch
    local = head if here else _rev(top, f"refs/heads/{branch}", env)
    if local is None:
        return {**out, "status": "not_updated", "reason": f"there is no local branch {branch}", "instead": f"`git -C {q} branch {shlex.quote(branch)} {shlex.quote('origin/' + branch)}` makes it"}
    out["from"] = local
    if local == remote:
        return {**out, "status": "current"}
    if not _is_ancestor(top, local, remote, env):
        return {**out, "status": "not_updated", "reason": _ahead_reason(top, local, remote, branch, env), "instead": f"`git -C {q} log {shlex.quote('origin/' + branch + '...' + branch)}` shows both sides; push, rebase or merge them yourself"}
    held = guard() if guard else None
    if held:
        return {**out, "status": "not_updated", "reason": held, "instead": f"the next try does it once that is over; or then {ff}"}
    if here:
        # The checkout must still be where it was judged: on the branch, at the commit that was checked as an ancestor.
        # 성진: a branch switch in the instant between this check and the merge is not held off (git has no compare-and-swap for a checkout); the result is checked after it instead.
        if _on(top, env) != (branch, local):
            return {**out, "status": "not_updated", "reason": "the checkout changed while it was being looked at", "instead": f"the next try does it; or {ff}"}
        code, _, err = run_git(top, *SAFE, *MERGE, remote, env=env, timeout=MERGE_SECONDS)
        if code != 0:
            hit = _overwritten(err)
            if hit is None:
                return {**out, "status": "failed", "reason": f"the fast-forward failed: {_last_line(err)}", "instead": ff}
            kind, files = hit
            n = len(files)
            if kind == "changed":
                what = f"you have changes to {n} file{'s' if n != 1 else ''} that the incoming commits also change"
            elif kind == "directory":
                what = f"the incoming commits put a file where {n} director{'ies' if n != 1 else 'y'} here hold{'' if n != 1 else 's'} files git does not track"
            else:
                what = f"{n} untracked or ignored file{'s' if n != 1 else ''} here would be overwritten by files the incoming commits add"
            return {**out, "status": "not_updated", "reason": what, "files": files[:FILES_SHOWN], "instead": f"commit, move or remove {'them' if n != 1 else 'it'}, then {ff}"}
        after = _on(top, env)
        if after != (branch, remote):
            return {**out, "status": "failed", "reason": f"the checkout changed while it was being updated: it is now on {after[0] or 'a detached HEAD'} at {(after[1] or '?')[:7]}", "instead": f"`git -C {q} status` and `git -C {q} log -1` show where it is"}
        status = "updated"
    else:
        # From the commit fetched, not the remote-tracking ref, which another fetch may have moved since. Through git, not update-ref: it refuses a branch checked out in any worktree and anything but a fast-forward.
        code, _, err = run_git(top, *SAFE, *FETCH, ".", f"{remote}:refs/heads/{branch}", env=env, timeout=MERGE_SECONDS)
        if code != 0:
            if "checked out at" in err or "refusing to fetch into" in err:
                return {**out, "status": "not_updated", "reason": f"{branch} is checked out in another worktree ({_last_line(err)})", "instead": f"update it there: `git merge --ff-only --no-overwrite-ignore {shlex.quote('origin/' + branch)}`"}
            return {**out, "status": "failed", "reason": f"moving {branch} failed: {_last_line(err)}", "instead": f"`git -C {q} fetch origin {shlex.quote(branch + ':' + branch)}`"}
        if _rev(top, f"refs/heads/{branch}", env) != remote:
            return {**out, "status": "failed", "reason": f"{branch} is not at the commit fetched after moving it", "instead": f"`git -C {q} log -1 {shlex.quote(branch)}` shows where it is"}
        status = "ref_updated"
    commits, more = _commits(top, local, remote, env)
    return {**out, "status": status, "files_updated": status == "updated", "commits": commits, "more": more}
