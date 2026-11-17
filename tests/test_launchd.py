"""The launchd unit's calendar: cron fields to `StartCalendarInterval`, as `man launchd.plist` defines it (missing keys are wildcards; Day and Weekday in one schedule fire on either), written out by hand."""

from __future__ import annotations

import plistlib
import unittest

from support.harness import engine

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


if __name__ == "__main__":
    unittest.main()
