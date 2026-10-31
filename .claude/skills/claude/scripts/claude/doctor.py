"""`doctor`: the environment a run would start in — claude and its version, login, the sandbox the profiles need, the account's usage limits, the registry, and settings that widen a profile. It starts no worker."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from claude.claude_cli import VERIFIED_VERSION, VERSION_FLOOR, VERSION_FLOOR_TEXT, auth_status, claude_version, profile_exceptions, quota, sandbox_prereqs, worker_env
from claude.git import main_checkout, toplevel, worktree_entries
from claude.registry import list_groups, live_runs, resolve_runs_dir
from claude.util import entry_path, invocation, skill_dir


def _text(v):
    return ".".join(str(x) for x in v)


def doctor(*, cwd, runs_dir=None):
    blockers, warnings = [], []
    if sys.version_info < (3, 11):
        blockers.append(f"Python {sys.version.split()[0]} is older than 3.11; run the skill through uv run")
    claude = claude_version()
    if claude["error"]:
        blockers.append(claude["error"])
    elif claude["parsed"] < VERSION_FLOOR:
        blockers.append(f"claude {claude['version']} is older than {VERSION_FLOOR_TEXT}, which the skill needs; update Claude Code")
    elif claude["parsed"] < VERIFIED_VERSION:
        warnings.append(f"claude {claude['version']} is older than {_text(VERIFIED_VERSION)}, the version this skill was verified against")
    auth = auth_status() if not claude["error"] else {"error": "no claude"}
    if auth.get("error"):
        blockers.append(f"login could not be read: {auth['error']}")
    elif not auth.get("loggedIn"):
        blockers.append("claude is not logged in; run `claude auth login` in a terminal")
    sandbox = sandbox_prereqs()
    if not sandbox["supported"]:
        warnings.append(f"the read-only and write profiles' sandbox is not supported on {sandbox['platform']}; only auto can run")
    elif sandbox["missing"]:
        warnings.append(f"the sandbox needs {', '.join(sandbox['missing'])}; read-only and write runs will fail to start until it is installed")
    limits = quota(worker_env(dict(os.environ), "doctor")) if not claude["error"] else {"error": "no claude"}
    if limits.get("error"):
        warnings.append(f"usage limits could not be read: {limits['error']}")
    else:
        for item in limits["limits"]:
            if isinstance(item.get("percent"), (int, float)) and item["percent"] >= 90:
                warnings.append(f"{item['kind']} limit at {item['percent']}% (resets {item['resets_at']}); every worker draws on it")
    registry = resolve_runs_dir(cwd, runs_dir)
    reg = {"path": registry, "exists": os.path.isdir(registry)}
    # Run commands create the registry with its missing parents, so what must be writable is the nearest folder that exists.
    probe = Path(registry)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    reg["writable"] = os.access(probe, os.W_OK)
    if not reg["writable"]:
        blockers.append(f"the registry {registry} cannot be written")
    reg["live_runs"] = [m.get("run_id") for _, m in live_runs(registry)] if reg["exists"] else []
    groups = list_groups(registry) if reg["exists"] else []
    reg["groups"] = [g["name"] for g in groups]
    # A worktree belongs to the group whose manifest records its exact path; names alone are ambiguous (fix-1 against fix-db-1).
    owner = {os.path.realpath((m.get("worktree") or {}).get("path") or ""): g["name"] for g in groups for m in g.get("members") or [] if (m.get("worktree") or {}).get("path")}
    repo = main_checkout(cwd)
    leftover = []
    if repo:
        for e in worktree_entries(repo):
            path = e["path"]
            if "/.claude/worktrees/" in path:
                leftover.append({"path": path, "branch": e["branch"], "group": owner.get(os.path.realpath(path))})
    reg["worktrees"] = leftover
    top = toplevel(cwd) or str(Path(cwd).resolve())
    roots = [r for r in {toplevel(cwd), repo} if r]
    exceptions = {p: profile_exceptions(top, p, project_roots=roots) for p in ("read-only", "write")}
    for p, items in exceptions.items():
        for item in items:
            if item["setting"] in ("sandbox.excludedCommands", "sandbox.enabled", "unreadable settings file"):
                warnings.append(f"{p}: {item['setting']} in {item['file']} — {item['effect']}")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": sorted(set(warnings), key=warnings.index),
        "python": sys.version.split()[0],
        "claude": {"path": claude["path"], "version": claude["version"], "floor": VERSION_FLOOR_TEXT, "verified": _text(VERIFIED_VERSION)},
        "auth": auth,
        "sandbox": sandbox,
        "quota": limits,
        "skill_dir": skill_dir(),
        "entry": entry_path(),
        "invocation": invocation("<command>"),
        "registry": reg,
        "profile_exceptions": exceptions,
    }
