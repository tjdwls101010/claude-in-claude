"""Group manifests under .claude-runs/.groups/: a name reserved by `batch` until `clean` releases it, and the members started under it."""

from __future__ import annotations

import re
from pathlib import Path

from claude.errors import Refusal
from claude.util import iso, now

from .locks import locked, read_json, write_json
from .runs import ensure_runs_dir

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def valid_group_name(name):
    return bool(NAME.match(name or ""))


def _path(runs_dir, name):
    return Path(runs_dir) / ".groups" / f"{name}.json"


def _lock(runs_dir, name):
    return locked(Path(runs_dir) / ".locks" / f"group-{name}.lock")


def claim_group(runs_dir, name, fields):
    """Reserve `name` and write its manifest with `fields`; Refusal when the name is already reserved."""
    ensure_runs_dir(runs_dir)
    (Path(runs_dir) / ".groups").mkdir(exist_ok=True)
    with _lock(runs_dir, name):
        if _path(runs_dir, name).exists():
            raise Refusal(f"group name {name!r} is reserved by an earlier batch until `clean` releases it", group=name)
        manifest = {"name": name, "created_at": now(), "created": iso(now()), "members": [], **fields}
        write_json(_path(runs_dir, name), manifest)
        return manifest


def record_members(runs_dir, name, members):
    with _lock(runs_dir, name):
        manifest = read_json(_path(runs_dir, name))
        if manifest is None:
            raise Refusal(f"group {name!r} was released while its members started")
        manifest["members"] = members
        manifest.pop("spawning_pid", None)
        write_json(_path(runs_dir, name), manifest)
        return manifest


def record_member(runs_dir, name, index, fields):
    """Update one member's entry as soon as its run exists, so an interrupted batch still leaves its live members in the group."""
    with _lock(runs_dir, name):
        manifest = read_json(_path(runs_dir, name))
        if manifest is None:
            return None
        for m in manifest.get("members") or []:
            if m.get("index") == index:
                m.update(fields)
        write_json(_path(runs_dir, name), manifest)
        return manifest


def group_view(runs_dir, name):
    """A group's manifest; Refusal when there is none or it does not parse."""
    try:
        manifest = read_json(_path(runs_dir, name))
    except ValueError as e:
        raise Refusal(f"the manifest of group {name!r} does not parse: {e}")
    if manifest is None:
        raise Refusal(f"no group {name!r} in {runs_dir}")
    return manifest


def release_group(runs_dir, name):
    with _lock(runs_dir, name):
        _path(runs_dir, name).unlink(missing_ok=True)


def list_groups(runs_dir):
    d = Path(runs_dir) / ".groups"
    out = []
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            m = read_json(p)
        except ValueError:
            continue
        if m:
            out.append(m)
    return out
