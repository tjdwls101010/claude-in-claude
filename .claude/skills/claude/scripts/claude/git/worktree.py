"""Linked worktrees through the git CLI: listing them, what a checkout holds beyond its commit and keeping that in git, removing one, and its branch."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from claude.util import nfc

from .repo import current_branch, head_commit, run_git, toplevel


def worktree_entries(repo):
    """Every worktree git knows for `repo`: path, head, branch, and whether it is locked, bare or prunable."""
    code, out, _ = run_git(repo, "worktree", "list", "--porcelain")
    if code != 0:
        return []
    entries = []
    for block in out.strip().split("\n\n"):
        e = {"path": None, "head": None, "branch": None, "locked": False, "bare": False, "prunable": False}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                e["path"] = nfc(value)
            elif key == "HEAD":
                e["head"] = value
            elif key == "branch":
                e["branch"] = value.removeprefix("refs/heads/")
            elif key in ("locked", "bare", "prunable"):
                e[key] = True
        if e["path"]:
            entries.append(e)
    return entries


def is_worktree(repo, path):
    real = os.path.realpath(path)
    return any(os.path.realpath(e["path"]) == real for e in worktree_entries(repo))


def fingerprint(path):
    """(kind, detail) of one entry: a file's sha256, a link's target, or a directory."""
    p = Path(path)
    if p.is_symlink():
        return ["link", os.readlink(p)]
    if p.is_dir():
        return ["dir", None]
    if p.is_file():
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return ["file", h.hexdigest()]
    return ["missing", None]


def status_entries(path):
    """(two-letter status, path) for every changed, untracked and ignored entry in the checkout at `path`, untracked and ignored listed file by file. None outside a work tree, or when git could not read a directory in it (so what it holds is not known)."""
    # traditional, unlike matching, lists the files inside an ignored directory one by one when untracked files are listed in full.
    # In English whatever the locale, since the warning below is read; and without refreshing the index, which would make the worktree look changed (`last_changed`).
    code, out, err = run_git(path, "status", "--porcelain=v1", "-z", "--ignored=traditional", "--untracked-files=all", env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"})
    # git skips a directory it cannot read with only a warning; what it holds is then unknown, not absent.
    if code != 0 or "could not open directory" in err:
        return None
    entries = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        xy, rel = item[:2], nfc(item[3:])
        if xy[0] in "RC":
            i += 1  # the rename's source follows as its own field
        entries.append((xy, rel))
    return entries


def is_include_copy(worktree, main, rel):
    """Whether `rel` in the worktree is a copy Claude Code made from the main checkout (`.worktreeinclude`): the same path there holds the same bytes."""
    source = Path(main) / rel
    target = Path(worktree) / rel
    if source.is_symlink() or target.is_symlink() or not source.is_file() or not target.is_file():
        return False
    return fingerprint(source) == fingerprint(target)


def startup_snapshot(worktree, main):
    """Untracked and ignored entries of a fresh worktree, each with its fingerprint, leaving out `.worktreeinclude` copies: what startup made before the worker's first tool call."""
    entries = status_entries(worktree) or []
    out = {}
    for xy, rel in entries:
        if xy not in ("??", "!!"):
            continue
        rel = rel.rstrip("/")
        if xy == "!!" and is_include_copy(worktree, main, rel):
            continue
        out[rel] = fingerprint(Path(worktree) / rel)
    return out


def leftovers(worktree, main, artifacts):
    """What a worktree holds beyond its commit that removing it would lose: changes to tracked files, untracked entries and ignored entries, leaving out `.worktreeinclude` copies and startup artifacts that are unchanged since they were recorded."""
    entries = status_entries(worktree)
    if entries is None:
        return None
    tracked, untracked, ignored = [], [], []
    artifacts = artifacts or {}
    for xy, rel in entries:
        rel = rel.rstrip("/")
        if xy == "??" or xy == "!!":
            if rel in artifacts and fingerprint(Path(worktree) / rel) == artifacts[rel]:
                continue
            if xy == "!!" and is_include_copy(worktree, main, rel):
                continue
            (untracked if xy == "??" else ignored).append(rel)
        else:
            tracked.append(rel)
    return {"tracked": tracked, "untracked": untracked, "ignored": ignored}


def unlock_and_remove(repo, path, force):
    """Unlock and remove a linked worktree. (ok, error text)."""
    run_git(repo, "worktree", "unlock", str(path))
    args = ["worktree", "remove"] + (["--force", "--force"] if force else []) + [str(path)]
    code, _, err = run_git(repo, *args)
    if code != 0:
        return False, err.strip()
    return True, None


def commits_beyond(repo, branch, base):
    """How many commits `branch` has that `base` does not, or None when either is unknown."""
    code, out, _ = run_git(repo, "rev-list", "--count", f"{base}..{branch}")
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def delete_branch(repo, branch):
    code, _, err = run_git(repo, "branch", "-D", branch)
    return code == 0, (err.strip() or None)


def prune_worktree(repo, path):
    """Forget the one worktree at `path` whose directory is gone, leaving git's other records alone."""
    run_git(repo, "worktree", "unlock", str(path))
    code, _, err = run_git(repo, "worktree", "remove", "--force", str(path))
    return code == 0, (err.strip() or None)


def detached_commits(repo, path, branch):
    """Commits the worktree at `path` holds on a detached HEAD that no branch contains, as a count, or 0."""
    entry = next((e for e in worktree_entries(repo) if os.path.realpath(e["path"]) == os.path.realpath(path)), None)
    if not entry or entry["branch"] or not entry["head"]:
        return 0
    code, out, _ = run_git(repo, "rev-list", "--count", entry["head"], "--not", "--branches")
    return int(out.strip()) if code == 0 and out.strip().isdigit() else 0


def last_changed(worktree):
    """When anything in the worktree at `worktree` last changed, as far as can be seen without writing to it: its index, the newest entry of its HEAD's reflog (commits, switches — the entry's own time, since `git gc` rewrites the log file without anything happening) and every changed, untracked or ignored entry, in epoch seconds; None when git cannot read it."""
    entries = status_entries(worktree)
    if entries is None:
        return None
    times = []
    code, out, _ = run_git(worktree, "rev-parse", "--git-path", "index")
    p = out.strip()
    if code == 0 and p:
        p = p if os.path.isabs(p) else os.path.join(worktree, p)
        if os.path.exists(p):
            times.append(os.lstat(p).st_mtime)
    code, out, _ = run_git(worktree, "reflog", "show", "-n1", "--date=unix", "--format=%gd", "HEAD")
    stamp = out.strip().rsplit("@{", 1)[-1].rstrip("}") if code == 0 else ""
    if stamp.isdigit():
        times.append(int(stamp))
    for _, rel in entries:
        p = Path(worktree) / rel.rstrip("/")
        if p.exists() or p.is_symlink():
            times.append(p.lstat().st_mtime)
    return max(times) if times else 0


def local_branches(repo):
    """The names of the repository's local branches."""
    code, out, _ = run_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return sorted(l for l in out.splitlines() if l.strip()) if code == 0 else []


def branch_tip(repo, branch):
    """The commit local `branch` points at, or None."""
    code, out, _ = run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    return out.strip() if code == 0 and out.strip() else None


def branch_exists(repo, branch):
    code, _, _ = run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    return code == 0


def status_snapshot(path):
    """The checkout at `path` as a scheduled run compares it before and after its worker (K27): `root` (the checkout's top level, which `entries` are relative to), `branch` (None when detached), `head`, and `entries`, every changed or untracked path under `path` — ignored files and .claude/worktrees left out — with its two-letter `status` and the `fingerprint` of what is there now. None outside a work tree."""
    root = toplevel(path)
    code, out, _ = run_git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", ":(exclude,top).claude/worktrees")
    if code != 0 or root is None:
        return None
    entries = {}
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        xy, rel = item[:2], nfc(item[3:])
        if xy[0] in "RC":
            i += 1  # the rename's source follows as its own field
        entries[rel] = {"status": xy, "fingerprint": fingerprint(Path(root) / rel)}
    return {"root": root, "branch": current_branch(path), "head": head_commit(path), "entries": entries}


def numstat(path, paths):
    """Lines added and deleted against HEAD, staged and unstaged together, for each of `paths` (relative to the checkout's top level, as `status_snapshot` gives them) git reports: `{path: [added, deleted]}`, or None for a binary file."""
    root = toplevel(path)
    if not paths or root is None:
        return {}
    code, out, _ = run_git(root, "diff", "HEAD", "--numstat", "-z", "--no-renames", "--", *paths)
    if code != 0:
        return {}
    return _numstat_lines(out)


def _numstat_lines(out):
    result = {}
    for item in out.split("\0"):
        fields = item.split("\t", 2)
        if len(fields) != 3:
            continue
        added, deleted, rel = fields
        result[nfc(rel)] = None if added == "-" else [int(added), int(deleted)]
    return result


def committed_files(path, base, head):
    """The files commits from `base` to `head` changed, in the repository at `path`: `[{status, path, lines}]` — `status` A, M or D, `lines` [added, deleted] or None for a binary file — in path order."""
    if not base or not head or base == head:
        return []
    code, out, _ = run_git(path, "diff", "--name-status", "-z", "--no-renames", base, head)
    if code != 0:
        return []
    parts = out.split("\0")
    changed = [(parts[i][:1], nfc(parts[i + 1])) for i in range(0, len(parts) - 1, 2) if parts[i]]
    code, out, _ = run_git(path, "diff", "--numstat", "-z", "--no-renames", base, head)
    counts = _numstat_lines(out) if code == 0 else {}
    return [{"status": st, "path": rel, "lines": counts.get(rel)} for st, rel in sorted(changed, key=lambda x: x[1])]


# What is left is copied into git objects whole; beyond this much the worktree stays where it is.
LEFTOVER_BYTES = 100 * 1024 * 1024
# git calls that read every leftover file, on a checkout that can be large (a vault of 17 GB); run_git's default is 30 s.
LEFTOVER_GIT_SECONDS = 600
# Local refs only: nothing pushes refs/claude/*, and the commits carry no one's name.
LEFTOVER_IDENTITY = {"GIT_AUTHOR_NAME": "claude skill", "GIT_AUTHOR_EMAIL": "claude-skill@localhost", "GIT_COMMITTER_NAME": "claude skill", "GIT_COMMITTER_EMAIL": "claude-skill@localhost"}


def _size(path):
    p = Path(path)
    if p.is_symlink() or not p.is_dir():
        return p.lstat().st_size if p.exists() or p.is_symlink() else 0
    return sum(f.lstat().st_size for f in p.rglob("*") if not f.is_dir() or f.is_symlink())


def preserve_leftovers(worktree, ref, main, artifacts):
    """Keep what the worktree at `worktree` holds beyond its commit — as `leftovers` counts it, so not unchanged startup artifacts — as two commits under `ref` (or `ref-2`, `ref-3` … when that is taken: a ref here is never moved) in its repository, so the worktree can be removed without losing it: `index_commit` (the index, its parent HEAD) and `commit` (every changed, untracked and ignored file byte for byte as it is on disk, its parent `index_commit`); `git worktree add <path> <commit>` brings the files back. A file the main checkout's `.worktreeinclude` names (it can be a secret) is never stored: an unchanged copy is left out, a changed one keeps the worktree. Returns `{ref, commit, index_commit, counts: {tracked, untracked, ignored}, bytes}`, with `commit` None when there is nothing to keep, or `{kept_because}` when it cannot be kept whole: an unresolved conflict, a repository of its own inside, a submodule with changes, more than LEFTOVER_BYTES, a git filter that would store other bytes than the disk holds, a file it could not read, or a step git refused. Nothing is changed in the worktree."""
    try:
        return _preserve(worktree, ref, main, artifacts)
    except OSError as e:
        return {"kept_because": f"it could not be read whole ({e})"}


def _include_paths(worktree, main):
    """Untracked and ignored paths in the worktree that the main checkout's `.worktreeinclude` names; None when git cannot say."""
    names = Path(main) / ".worktreeinclude"
    if not names.is_file():
        return set()
    code, out, _ = run_git(worktree, "ls-files", "-z", "--others", "--ignored", f"--exclude-from={names}", timeout=LEFTOVER_GIT_SECONDS)
    return {nfc(p) for p in out.split("\0") if p} if code == 0 else None


def _blobs(worktree, commit, git_out):
    """{path: blob id} of the files in `commit`."""
    out = {}
    for item in git_out("ls-tree", "-r", "-z", commit, strip=False).split("\0"):
        meta, _, rel = item.partition("\t")
        if rel:
            out[nfc(rel)] = meta.split(" ")[2]
    return out


def _preserve(worktree, ref, main, artifacts):
    left = leftovers(worktree, main, artifacts)
    if left is None:
        return {"kept_because": "git cannot read all of it, so what it holds is not known"}
    included = _include_paths(worktree, main)
    if included is None:
        return {"kept_because": "the files .worktreeinclude names could not be told apart"}
    for rel in sorted(included):
        if not is_include_copy(worktree, main, rel):
            return {"kept_because": f"{rel}, which .worktreeinclude names (it may hold a secret), differs from the main checkout's, and such a file is never stored in git"}
    for kind in ("untracked", "ignored"):
        left[kind] = [rel for rel in left[kind] if rel not in included]
    counts = {k: len(v) for k, v in left.items()}
    if not any(counts.values()):
        return {"ref": ref, "commit": None, "index_commit": None, "counts": counts, "bytes": 0}
    code, out, _ = run_git(worktree, "ls-files", "--unmerged")
    if code != 0 or out.strip():
        return {"kept_because": "its index has unresolved conflicts"}
    for rel in left["untracked"] + left["ignored"]:
        if (Path(worktree) / rel / ".git").exists():
            return {"kept_because": f"{rel} is a repository of its own"}
    code, out, _ = run_git(worktree, "status", "--porcelain=v2", "--ignore-submodules=none", env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if any(line.startswith(("1 ", "2 ")) and line.split(" ")[2].startswith("S") and line.split(" ")[2] != "S..." for line in out.splitlines()):
        return {"kept_because": "a submodule in it has changes"}
    total = sum(_size(Path(worktree) / rel) for rel in left["tracked"] + left["untracked"] + left["ignored"])
    if total > LEFTOVER_BYTES:
        return {"kept_because": f"what is left in it comes to {total // (1024 * 1024)} MiB, over the 100 MiB kept in git"}
    env = {**os.environ, **LEFTOVER_IDENTITY}
    message = f"Left in {worktree} when its work had landed"

    def git_out(*args, index=None, strip=True):
        code, out, err = run_git(worktree, *args, env={**env, "GIT_INDEX_FILE": index} if index else env, timeout=LEFTOVER_GIT_SECONDS)
        if code != 0:
            raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else f"git {args[0]} failed")
        return out.strip() if strip else out

    with tempfile.TemporaryDirectory() as tmp:
        index = os.path.join(tmp, "index")
        try:
            head = git_out("rev-parse", "HEAD")
            # A copy of the worktree's own index: `add` then hashes only what changed (from `read-tree` it would hash every tracked file), and the real index is never written, so the worktree does not look changed afterwards (`last_changed`).
            real = git_out("rev-parse", "--git-path", "index")
            shutil.copyfile(real if os.path.isabs(real) else os.path.join(worktree, real), index)
            index_tree = git_out("write-tree", index=index)
            index_commit = git_out("commit-tree", index_tree, "-p", head, "-m", f"{message}: the index")
            git_out("add", "--all", "--force", "--", ".", index=index)
            # What is not kept stays out of git: startup artifacts, and the files .worktreeinclude names, which `add --force` just took. Paths as they are, not as patterns.
            keep = set(left["untracked"] + left["ignored"])
            dropped = sorted({rel.rstrip("/") for xy, rel in (status_entries(worktree) or []) if xy in ("??", "!!") and rel.rstrip("/") not in keep} | included)
            if dropped:
                git_out("--literal-pathspecs", "rm", "--cached", "-r", "-q", "--ignore-unmatch", "--", *dropped, index=index)
            tree = git_out("write-tree", index=index)
            commit = git_out("commit-tree", tree, "-p", index_commit, "-m", f"{message}: every file")
            blobs = _blobs(worktree, commit, git_out)
            files = [rel for rel in left["tracked"] + left["untracked"] + left["ignored"] if (Path(worktree) / rel).exists() or (Path(worktree) / rel).is_symlink()]
            missing = [rel for rel in files if rel not in blobs]
            if missing:
                return {"kept_because": f"{len(missing)} file(s) did not make it into git, such as {missing[0]}"}
            plain = [rel for rel in files if (Path(worktree) / rel).is_file() and not (Path(worktree) / rel).is_symlink()]
            differ = []
            for i in range(0, len(plain), 200):
                chunk = plain[i:i + 200]
                differ += [rel for rel, sha in zip(chunk, git_out("hash-object", "--no-filters", "--", *chunk).split()) if blobs[rel] != sha]
            if differ:
                return {"kept_because": f"{len(differ)} file(s) would be kept with bytes that differ from the disk (a git filter changes them), such as {differ[0]}"}
            for n in range(1, 100):
                name = ref if n == 1 else f"{ref}-{n}"
                # Created, never moved: an earlier keeping under this name stays.
                if run_git(worktree, "update-ref", name, commit, "", env=env)[0] == 0:
                    return {"ref": name, "commit": commit, "index_commit": index_commit, "counts": counts, "bytes": total}
            return {"kept_because": f"{ref} and the next 98 names after it are taken"}
        except RuntimeError as e:
            return {"kept_because": f"git refused to keep them: {e}"}
