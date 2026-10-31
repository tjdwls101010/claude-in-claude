"""File locks and atomic JSON files, the two primitives every registry write goes through."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path


@contextlib.contextmanager
def locked(path):
    """An exclusive flock on `path`, created if missing, held for the block. Released by the kernel if the holder dies."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def write_json(path, obj):
    """Write `obj` to `path` so a reader sees the old file or the new one, never half of either."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path):
    """The object in `path`, None when the file is missing; a file that does not parse raises ValueError."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return obj
