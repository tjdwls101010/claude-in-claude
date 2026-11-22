"""LaunchAgents through launchd: the plist that starts a program on calendar times in the Mac's own time zone, loading and unloading it in the user's GUI domain, and what is loaded. launchd fires a time missed in sleep once on wake, coalescing several (man launchd.plist)."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from itertools import product
from pathlib import Path
from xml.parsers.expat import ExpatError

# A dispatcher with more calendar entries than this is refused; ask for a coarser time (K6).
CALENDAR_LIMIT = 500
# What a file name holds on this Mac, in UTF-16 units (measured on APFS: 255 Korean or ASCII characters fit, 256 do not; emoji, two units each, stop at 127).
FILE_NAME_UNITS = 255
KEYS = (("minute", "Minute"), ("hour", "Hour"), ("month", "Month"))


def supported():
    """Whether this platform has launchd."""
    return sys.platform == "darwin" and bool(shutil.which("launchctl"))


def agents_dir():
    return Path(os.path.expanduser("~")) / "Library" / "LaunchAgents"


def _domain():
    return f"gui/{os.getuid()}"


def _launchctl(*args):
    try:
        proc = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return proc.returncode, (proc.stderr or proc.stdout).strip()


def calendar_entries(fields):
    """`StartCalendarInterval` for cron-style fields (`minute`, `hour`, `day`, `month`, `weekday` as value lists, None for any): one dictionary per combination of the restricted fields; with both day and weekday restricted, the day dictionaries and the weekday dictionaries, either of which fires, as in cron. ValueError beyond CALENDAR_LIMIT."""
    base = [(key, fields.get(name)) for name, key in KEYS if fields.get(name) is not None]

    def combos(extra):
        items = base + extra
        names = [k for k, _ in items]
        return [dict(zip(names, values)) for values in product(*[v for _, v in items])]

    day, weekday = fields.get("day"), fields.get("weekday")
    if day is not None and weekday is not None:
        entries = combos([("Day", day)]) + combos([("Weekday", weekday)])
    elif day is not None:
        entries = combos([("Day", day)])
    elif weekday is not None:
        entries = combos([("Weekday", weekday)])
    else:
        entries = combos([])
    if len(entries) > CALENDAR_LIMIT:
        raise ValueError(f"this time needs {len(entries)} launchd calendar entries, more than {CALENDAR_LIMIT}; choose a coarser time")
    return entries


def render_agent(label, argv, calendar, log):
    """The plist of an agent that runs `argv` at the `calendar` times, its output appended to `log`."""
    return plistlib.dumps({"Label": label, "ProgramArguments": list(argv), "StartCalendarInterval": calendar, "StandardOutPath": str(log), "StandardErrorPath": str(log), "RunAtLoad": False, "ProcessType": "Background"}).decode("utf-8")


def label_problem(label):
    """Why an agent of this label cannot be installed, in words, or None: its plist is the file `<label>.plist`."""
    units = len(f"{label}.plist".encode("utf-16-le", "surrogatepass")) // 2
    if units > FILE_NAME_UNITS:
        return f"its plist's file name would be {units} UTF-16 units, and a file name on this Mac holds {FILE_NAME_UNITS}"
    return None


def agent_identity(label):
    """Whose plist sits at `label`'s path: `{label, argv, plist}` from its `Label` and `ProgramArguments` (`label` None and `argv` empty when it cannot be read), or None when there is no file. One label's path can hold another's agent: this file system ignores letter case and Unicode form, and launchd's labels do not."""
    path = agents_dir() / f"{label}.plist"
    try:
        data = plistlib.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValueError, ExpatError):
        data = None
    there, argv = (data.get("Label"), data.get("ProgramArguments")) if isinstance(data, dict) else (None, None)
    return {"label": there if isinstance(there, str) else None, "argv": [str(a) for a in argv] if isinstance(argv, list) else [], "plist": str(path)}


def _foreign(label):
    """The identity at `label`'s path when it is not `label`'s own, else None."""
    held = agent_identity(label)
    return held if held is not None and held["label"] != label else None


def install_agent(label, argv, calendar, log):
    """Write the agent's plist to ~/Library/LaunchAgents and load it, replacing its own earlier one. Returns `{status: installed, label, plist}`, or `{status: failed, label, plist, error}` — also when the path holds another agent's plist or one that cannot be read, which is left as it is."""
    path = agents_dir() / f"{label}.plist"
    other = _foreign(label)
    if other:
        return {"status": "failed", "label": label, "plist": str(path), "error": f"{path} holds " + (f"the plist of another agent, {other['label']}" if other["label"] else "a plist that cannot be read") + "; it was left alone"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_agent(label, argv, calendar, log), encoding="utf-8")
    except OSError as e:
        return {"status": "failed", "label": label, "plist": str(path), "error": f"could not write the plist: {e}"}
    _launchctl("bootout", f"{_domain()}/{label}")
    code, err = _launchctl("bootstrap", _domain(), str(path))
    if code != 0:
        return {"status": "failed", "label": label, "plist": str(path), "error": f"launchctl bootstrap exited {code}: {err}"}
    return {"status": "installed", "label": label, "plist": str(path)}


def remove_agent(label):
    """Unload the agent and delete its plist. `{status: removed | absent | failed, label, plist}` (with `error` when failed). A plist at its path that is another agent's, or cannot be read, is left as it is, and the reply then carries `other`: that agent's label, None for an unreadable one."""
    path = agents_dir() / f"{label}.plist"
    other = _foreign(label)
    reply = {"label": label, "plist": str(path), **({"other": other["label"]} if other else {})}
    loaded = agent_state(label) == "loaded"
    if not loaded and (other or not path.exists()):
        return {"status": "absent", **reply}
    if loaded:
        code, err = _launchctl("bootout", f"{_domain()}/{label}")
        if code != 0 and agent_state(label) == "loaded":
            return {"status": "failed", **reply, "error": f"launchctl bootout exited {code}: {err}"}
    if not other:
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            return {"status": "failed", **reply, "error": f"could not delete the plist: {e}"}
    return {"status": "removed", **reply}


def agent_state(label):
    """`loaded`, `unloaded` (its plist exists but launchd does not run it) or `missing`."""
    code, _ = _launchctl("print", f"{_domain()}/{label}")
    if code == 0:
        return "loaded"
    return "unloaded" if (agents_dir() / f"{label}.plist").exists() else "missing"


def list_agents(prefix):
    """The labels of the plists in ~/Library/LaunchAgents whose label starts with `prefix`."""
    d = agents_dir()
    return sorted(p.stem for p in d.glob(f"{prefix}*.plist")) if d.is_dir() else []


def system_timezone():
    """The IANA name of the time zone launchd fires in — this Mac's (/etc/localtime) — or None."""
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return None
    marker = "/zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else None
