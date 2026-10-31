"""Reading a repository through the git CLI: its top level, its main checkout, its HEAD and how much is uncommitted."""

from __future__ import annotations

import os
import subprocess

from claude.util import nfc


def run_git(cwd, *args, timeout=30):
    """(returncode, stdout, stderr) of `git -C cwd args…`; a missing git or directory is a failure, not an exception."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def toplevel(path):
    """The top level of the checkout `path` is in, or None outside a git work tree."""
    code, out, _ = run_git(path, "rev-parse", "--show-toplevel")
    return nfc(out.strip()) if code == 0 and out.strip() else None


def main_checkout(path):
    """The repository's main checkout: the first `git worktree list` record, seen the same from any linked worktree. A bare repository has no main checkout, and a submodule is its own, so both answer with the checkout `path` is in. None outside a git work tree."""
    top = toplevel(path)
    if top is None:
        return None
    code, out, _ = run_git(path, "worktree", "list", "--porcelain")
    if code != 0:
        return top
    first = out.split("\n\n", 1)[0].splitlines()
    worktree = next((l[len("worktree "):] for l in first if l.startswith("worktree ")), None)
    if worktree is None or "bare" in first:
        return top
    worktree = nfc(worktree)
    # A submodule's list starts at its git directory under the superproject's .git/modules, which is not a checkout: only a record that is its own top level is one.
    if not os.path.isdir(worktree) or toplevel(worktree) != worktree:
        return top
    return worktree


def head_commit(path):
    code, out, _ = run_git(path, "rev-parse", "--verify", "-q", "HEAD")
    return out.strip() if code == 0 and out.strip() else None


def uncommitted_count(path):
    """Entries `git status` shows as changed or untracked (ignored files not counted), or None outside a work tree."""
    code, out, _ = run_git(path, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        return None
    return sum(1 for l in out.splitlines() if l.strip())
