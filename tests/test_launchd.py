"""The launchd unit's calendar: cron fields to `StartCalendarInterval`, as `man launchd.plist` defines it (missing keys are wildcards; Day and Weekday in one schedule fire on either), written out by hand. And whose plist a path holds: this Mac's file system ignores letter case and Unicode form (measured: a directory made as `Case_Test` exists as `case_test`), so the path of one label can hold another label's agent, which installing and removing must leave alone."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support.harness import FAKE_LAUNCHCTL_DIR, FIXTURES, engine

launchd = engine("claude.launchd")
schedule = engine("claude.schedule")


def entries(expr):
    return launchd.calendar_entries(schedule.parse_cron(expr))


class Calendar(unittest.TestCase):
    def test_daily(self):
        self.assertEqual(entries("0 3 * * *"), [{"Minute": 0, "Hour": 3}])

    def test_weekdays(self):
        self.assertEqual(entries("30 9 * * 1-5"), [{"Minute": 30, "Hour": 9, "Weekday": d} for d in (1, 2, 3, 4, 5)])

    def test_day_or_weekday(self):
        self.assertEqual(entries("0 12 1 * 1"), [{"Minute": 0, "Hour": 12, "Day": 1}, {"Minute": 0, "Hour": 12, "Weekday": 1}])

    def test_quarter_hours_and_months(self):
        self.assertEqual(entries("*/15 * * * *"), [{"Minute": 0}, {"Minute": 15}, {"Minute": 30}, {"Minute": 45}])
        self.assertEqual(entries("0 0 31 1,3 *"), [{"Minute": 0, "Hour": 0, "Month": 1, "Day": 31}, {"Minute": 0, "Hour": 0, "Month": 3, "Day": 31}])

    def test_too_many_entries(self):
        with self.assertRaises(ValueError) as cm:
            entries("*/5 0-23 1-31 * *")
        self.assertIn("8928", str(cm.exception))

    def test_plist(self):
        text = launchd.render_agent("claude-schedule.o-r.n", ["/opt/homebrew/bin/gh", "workflow", "run", "claude-n.yml"], [{"Minute": 0, "Hour": 3}], "/h/Library/Logs/claude-schedule/o-r.n.log")
        d = plistlib.loads(text.encode())
        self.assertEqual(d["Label"], "claude-schedule.o-r.n")
        self.assertEqual(d["StartCalendarInterval"], [{"Minute": 0, "Hour": 3}])
        self.assertEqual(d["StandardOutPath"], d["StandardErrorPath"])
        self.assertFalse(d["RunAtLoad"])


class Ownership(unittest.TestCase):
    """In a private HOME with the fake launchctl. The other agent's plist is planted at this label's own path, which is what a file system that ignores case does to `…Nightly` and `…nightly`."""

    MINE, THEIRS = "claude-schedule.o-r.nightly", "claude-schedule.o-r.NIGHTLY"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="cic-home-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        patched = mock.patch.dict(os.environ, {"HOME": str(self.home), "PATH": os.pathsep.join([str(FAKE_LAUNCHCTL_DIR), os.environ.get("PATH", "")]), "FAKE_LAUNCHCTL_STATE": str(self.home / "launchctl")})
        patched.start()
        self.addCleanup(patched.stop)

    def path(self, label):
        return self.home / "Library" / "LaunchAgents" / f"{label}.plist"

    def plant(self, label, at=None, argv=("/bin/echo", "theirs")):
        data = plistlib.dumps({"Label": label, "ProgramArguments": list(argv)})
        self.path(at or label).write_bytes(data)
        return data

    def launchctl_calls(self):
        d = self.home / "launchctl" / "calls"
        return [json.loads(p.read_text())["argv"][0] for p in sorted(d.glob("*.json"))] if d.exists() else []

    def test_identity_is_what_the_plist_at_the_path_says(self):
        self.assertIsNone(launchd.agent_identity(self.MINE))
        self.plant(self.THEIRS, at=self.MINE, argv=("/bin/gh", "workflow", "run", "x.yml", "--repo", "o/r"))
        self.assertEqual(launchd.agent_identity(self.MINE), {"label": self.THEIRS, "argv": ["/bin/gh", "workflow", "run", "x.yml", "--repo", "o/r"], "plist": str(self.path(self.MINE))})
        self.path(self.MINE).write_text("not a plist")
        self.assertEqual(launchd.agent_identity(self.MINE), {"label": None, "argv": [], "plist": str(self.path(self.MINE))})

    def test_a_dispatcher_0_2_0_installed_reads_as_itself(self):
        label = "claude-schedule.tjdwls101010-claude-schedule-probe.nightly"
        shutil.copy(FIXTURES / "launchd" / "dispatcher-0.2.0.plist", self.path(label))
        found = launchd.agent_identity(label)
        self.assertEqual(found["label"], label)
        self.assertEqual(found["argv"][found["argv"].index("--repo") + 1], "tjdwls101010/claude-schedule-probe")

    def test_installing_leaves_another_agents_plist_alone(self):
        before = self.plant(self.THEIRS, at=self.MINE)
        reply = launchd.install_agent(self.MINE, ["/bin/echo", "mine"], [{"Minute": 0}], str(self.home / "log"))
        self.assertEqual(reply["status"], "failed")
        self.assertIn(self.THEIRS, reply["error"])
        self.assertEqual(self.path(self.MINE).read_bytes(), before)
        self.assertNotIn("bootstrap", self.launchctl_calls())

    def test_installing_replaces_its_own(self):
        self.plant(self.MINE, argv=("/bin/echo", "old"))
        reply = launchd.install_agent(self.MINE, ["/bin/echo", "new"], [{"Minute": 0}], str(self.home / "log"))
        self.assertEqual(reply["status"], "installed")
        self.assertEqual(launchd.agent_identity(self.MINE)["argv"], ["/bin/echo", "new"])

    def test_removing_leaves_another_agents_plist_alone(self):
        before = self.plant(self.THEIRS, at=self.MINE)
        reply = launchd.remove_agent(self.MINE)
        self.assertEqual((reply["status"], reply["other"]), ("absent", self.THEIRS))
        self.assertEqual(self.path(self.MINE).read_bytes(), before)
        self.path(self.MINE).write_text("not a plist")
        reply = launchd.remove_agent(self.MINE)
        self.assertEqual((reply["status"], reply["other"]), ("absent", None))
        self.assertTrue(self.path(self.MINE).exists(), "a plist that cannot be read is not known to be this agent's")

    def test_removing_its_own(self):
        launchd.install_agent(self.MINE, ["/bin/echo", "mine"], [{"Minute": 0}], str(self.home / "log"))
        reply = launchd.remove_agent(self.MINE)
        self.assertEqual(reply["status"], "removed")
        self.assertNotIn("other", reply)
        self.assertFalse(self.path(self.MINE).exists())


if __name__ == "__main__":
    unittest.main()
