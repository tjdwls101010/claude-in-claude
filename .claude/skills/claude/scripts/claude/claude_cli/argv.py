"""How a worker is started: the argv for one `claude -p` process, the environment it gets, the standing context appended to its system prompt, and the settings files that widen a profile."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROFILES = ("read-only", "write", "auto")

# Tools no worker gets: the skill itself (a worker cannot start workers), Monitor (its notifications keep a finished run alive for as long as the watched command runs), and tools whose effect outlives the turn or bypasses the registry.
ALWAYS_DISALLOWED = ("Skill(claude)", "Skill(claude:claude)", "Monitor", "SendMessage", "PushNotification", "CronCreate", "RemoteTrigger")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")

# Writable for every sandboxed profile besides the sandbox's own TMPDIR: tool caches (uv, pip, npm) live here, so a read-only run can still run a project's tests.
SANDBOX_CACHE = "~/.cache"

PERMISSION_MODE = {"read-only": "dontAsk", "write": "acceptEdits", "auto": "auto"}

# The parent session's identity, which a worker must not inherit: it would otherwise report to or message as the session that started it.
PARENT_IDENTITY = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_BRIDGE_SESSION_ID", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ATTENDED")
RUN_VARIABLE = "CLAUDE_SKILL_RUN"
# With background work off, a turn's end is the run's end. The Bash ceilings let a foreground command run 10 minutes without a timeout and up to an hour with one, since nothing can move to the background.
FIXED_ENV = {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}
MINIMUM_ENV = {"BASH_DEFAULT_TIMEOUT_MS": 600000, "BASH_MAX_TIMEOUT_MS": 3600000}

WORKER_CONTEXT = (
    "You are a non-interactive worker: another Claude session (the caller) started you through a skill and reads only your final message. "
    "Nobody can answer a question or a permission prompt during your turn, so when something is ambiguous, choose the most reasonable interpretation, act on it, and state the assumption in your final message. "
    "Make the final message self-contained: what you did, what you found, what you changed, and what you could not do and why. "
    "Do not commit, create branches, push, open pull requests or merge unless the prompt asks you to; list the files you changed instead. "
    "You cannot start other workers."
)


def turn_preamble(profile, *, group=None, worktree=None):
    """What this turn's prompt is prefixed with: the group a batch member belongs to and a worktree member's checkout. None when there is nothing to say."""
    lines = []
    if group:
        lines.append(f"[You are member {group['index']} of {group['size']} in group {group['name']}, started together on related tasks; the others work in parallel and you will not see their work.]")
    if worktree:
        lines.append(f"[You are working in a git worktree at {worktree['path']}, not the caller's checkout. It was created from commit {worktree['base']}; the caller's tree has {worktree['uncommitted']} uncommitted file(s) that are not here.]")
    return "\n".join(lines) or None


def worker_context():
    """The standing facts appended to every turn's system prompt. The same text every turn, so a resumed session reads what it was started with."""
    return WORKER_CONTEXT


def sandbox_settings(profile, cwd):
    if profile == "auto":
        return None
    filesystem = {"allowWrite": [SANDBOX_CACHE]}
    if profile == "read-only":
        filesystem = {"denyWrite": [cwd], "allowWrite": [SANDBOX_CACHE]}
    return {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True, "filesystem": filesystem}


def build_argv(settings, *, session_id, resume, cwd, worktree=None, schema_text=None):
    """The argv for one turn's process. Every turn carries the whole profile, model, effort and schema, because `-p --resume` restores the model but not the permission mode or the schema."""
    profile = settings["profile"]
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    disallowed = list(ALWAYS_DISALLOWED) + (list(EDIT_TOOLS) if profile == "read-only" else [])
    flag_settings = {}
    sandbox = sandbox_settings(profile, cwd)
    if sandbox:
        flag_settings["sandbox"] = sandbox
    if worktree:
        flag_settings["worktree"] = {"baseRef": "head"}
    argv = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--include-hook-events", "--permission-prompts", "none"]
    argv += ["--permission-mode", PERMISSION_MODE[profile], "--model", settings["model"], "--effort", settings["effort"]]
    if sandbox:
        # Sandbox auto-allow leaves some shell forms (a loop, `$?`) to the permission check, which nobody can answer here; approving Bash outright keeps the sandbox as the boundary for every form.
        argv += ["--allowedTools", "Bash"]
    argv += ["--append-system-prompt", WORKER_CONTEXT]
    # Variadic: every token after it up to the next flag is a tool name, so a flag must follow.
    argv += ["--disallowedTools", *disallowed]
    argv += ["--resume", session_id] if resume else ["--session-id", session_id]
    if flag_settings:
        argv += ["--settings", json.dumps(flag_settings)]
    if schema_text is not None:
        argv += ["--json-schema", schema_text]
    if worktree:
        argv += ["--worktree", worktree]
    return argv


def worker_env(base_env, run_id):
    """The worker's environment: the supervisor's own, minus the parent session's identity, plus the run marker and the foreground-only settings."""
    env = {k: v for k, v in base_env.items() if k not in PARENT_IDENTITY}
    env[RUN_VARIABLE] = run_id
    env.update(FIXED_ENV)
    for key, floor in MINIMUM_ENV.items():
        try:
            current = int(env.get(key, ""))
        except ValueError:
            current = 0
        env[key] = str(max(current, floor))
    return env


def worktree_location(repo, name):
    """Where Claude Code's `--worktree <name>` puts a checkout and the branch it creates."""
    return {"path": str(Path(repo) / ".claude" / "worktrees" / name), "branch": f"worktree-{name}"}


def default_managed_dir():
    if sys.platform == "darwin":
        return "/Library/Application Support/ClaudeCode"
    return "/etc/claude-code"


def settings_files(cwd, *, env, managed_dir, project_roots):
    """Every settings file a worker started in `cwd` reads, as (scope, path): user, project and local for each project root, and managed."""
    config = env.get("CLAUDE_CONFIG_DIR") or str(Path(env.get("HOME") or os.path.expanduser("~")) / ".claude")
    files = [("user", Path(config) / "settings.json")]
    roots = []
    for root in [cwd, *project_roots]:
        if root and str(root) not in roots:
            roots.append(str(root))
    for root in roots:
        files.append(("project", Path(root) / ".claude" / "settings.json"))
        files.append(("local", Path(root) / ".claude" / "settings.local.json"))
    managed = Path(managed_dir or default_managed_dir())
    files.append(("managed", managed / "managed-settings.json"))
    dropins = managed / "managed-settings.d"
    if dropins.is_dir():
        files += [("managed", p) for p in sorted(dropins.glob("*.json"))]
    return files


def _get(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _outside(rule_path, cwd):
    """Whether an Edit/Write rule's path names somewhere outside `cwd`: absolute (`/…`, `//…`) or home (`~/…`) paths that do not lie under it."""
    if rule_path.startswith("//"):
        path = rule_path[1:]
    elif rule_path.startswith("~"):
        path = os.path.expanduser(rule_path)
    elif rule_path.startswith("/"):
        path = rule_path
    else:
        return False
    base = path.split("*", 1)[0].rstrip("/") or "/"
    cwd = str(cwd).rstrip("/")
    return not (base == cwd or base.startswith(cwd + "/"))


SANDBOXED = ("read-only", "write")


def profile_exceptions(cwd, profile, *, env=None, managed_dir=None, project_roots=()):
    """Settings in the files a worker reads that widen what `profile` allows, one entry per setting and file: `setting`, `file`, `value`, `effect`. A profile is a restriction laid over these settings, not a replacement for them."""
    env = os.environ if env is None else env
    found = []
    for scope, path in settings_files(cwd, env=env, managed_dir=managed_dir, project_roots=project_roots):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            found.append({"setting": "unreadable settings file", "file": str(path), "value": None, "effect": f"could not be read ({e}); whatever it sets still applies to the worker"})
            continue

        def add(setting, value, effect):
            found.append({"setting": setting, "file": str(path), "value": value, "effect": effect})

        if profile in SANDBOXED:
            if value := _get(data, "sandbox", "excludedCommands"):
                add("sandbox.excludedCommands", value, "these commands run outside the sandbox, approved like every shell command: unrestricted writes and network")
            if value := _get(data, "sandbox", "filesystem", "allowWrite"):
                add("sandbox.filesystem.allowWrite", value, "sandboxed commands can also write here")
            if value := _get(data, "sandbox", "network", "allowedDomains"):
                add("sandbox.network.allowedDomains", value, "sandboxed commands can reach these hosts")
            allow = _get(data, "permissions", "allow") or []
            domains = [r[len("WebFetch(domain:"):-1] for r in allow if isinstance(r, str) and r.startswith("WebFetch(domain:") and r.endswith(")")]
            if domains:
                add("permissions.allow WebFetch(domain:…)", domains, "WebFetch can fetch these hosts, and sandboxed commands can reach them too")
            outside = [r for r in allow if isinstance(r, str) and r.split("(", 1)[0] in ("Edit", "Write") and r.endswith(")") and _outside(r.split("(", 1)[1][:-1], cwd)]
            if outside:
                add("permissions.allow Edit/Write outside", outside, "the edit tools can write these paths outside the working directory")
            if value := _get(data, "permissions", "additionalDirectories"):
                add("permissions.additionalDirectories", value, "sandboxed writes and accepted edits extend to these directories")
            if scope == "managed" and _get(data, "sandbox", "enabled") is False:
                add("sandbox.enabled", False, "managed settings turn the sandbox off: shell commands run unsandboxed")
        settings_env = _get(data, "env") or {}
        for key in ("BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"):
            if isinstance(settings_env, dict) and key in settings_env:
                add(f"env.{key}", settings_env[key], "overrides the value the skill gives the worker, since settings env wins over the process environment")
    return found
