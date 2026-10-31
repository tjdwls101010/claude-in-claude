"""Linked worktrees through the git CLI: listing them, what a checkout holds beyond its commit, removing one, and its branch."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from claude.util import nfc

from .repo import run_git


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
    """(two-letter status, path) for every changed, untracked and ignored entry in the checkout at `path`, untracked and ignored listed file by file. None outside a work tree."""
    # traditional, unlike matching, lists the files inside an ignored directory one by one when untracked files are listed in full.
    code, out, _ = run_git(path, "status", "--porcelain=v1", "-z", "--ignored=traditional", "--untracked-files=all")
    if code != 0:
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


def branch_exists(repo, branch):
    code, _, _ = run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    return code == 0
