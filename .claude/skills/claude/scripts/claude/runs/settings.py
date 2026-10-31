"""What a turn runs with: profile, model, effort and schema, taken from the command's flags, then from the session's last recorded run, then from the skill's defaults. The defaults are the skill's own, not the user's settings.json, so a run's model and effort never depend on which settings file a worker happens to read."""

from __future__ import annotations

from pathlib import Path

from claude.claude_cli import PROFILES
from claude.errors import Refusal

DEFAULTS = {"profile": "write", "model": "sonnet", "effort": "high"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def read_schema(path):
    """The text of a --schema file, which must hold one JSON object."""
    import json

    p = Path(path).expanduser()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise Refusal(f"--schema {path}: {e.strerror or e}", arguments=True, help="start --help")
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise Refusal(f"--schema {path} is not JSON: {e}", arguments=True, help="start --help")
    if not isinstance(obj, dict):
        raise Refusal(f"--schema {path} must hold a JSON object", arguments=True, help="start --help")
    return json.dumps(obj, ensure_ascii=False)


def settings_for(flags, record=None):
    """The settings for one run. `flags` holds what the command line gave (None for absent): profile, model, effort, schema (a path). `record` is the session's previous run settings, or None for a new session or one this registry never saw; a session the registry never saw needs a profile, since nothing says what it was allowed before."""
    if record is None and flags.get("resume") and not flags.get("profile"):
        raise Refusal("this session is not in the registry, so its profile is unknown; pass --profile", arguments=True, help="resume --help")
    base = dict(DEFAULTS)
    if record:
        base.update({k: record[k] for k in ("profile", "model", "effort") if record.get(k)})
        base["schema_text"] = record.get("schema_text")
    else:
        base["schema_text"] = None
    out = dict(base)
    for key in ("profile", "model", "effort"):
        if flags.get(key):
            out[key] = flags[key]
    if out["profile"] not in PROFILES:
        raise Refusal(f"unknown profile {out['profile']!r}", arguments=True, help="start --help")
    if out["effort"] not in EFFORTS:
        raise Refusal(f"unknown effort {out['effort']!r}", arguments=True, help="start --help")
    if flags.get("schema"):
        out["schema_text"] = read_schema(flags["schema"])
    out["changed"] = {k: base[k] for k in ("profile", "model", "effort") if record and base[k] != out[k]}
    return out
