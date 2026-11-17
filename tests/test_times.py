"""When a schedule fires (K4·K6): the slot an automatic trigger fills and the next fire times, from cron or a one-off --at, in a named time zone. Expected epochs were computed with `TZ=<zone> date -j -f` and weekdays read off `cal`, not with the code under test."""

from __future__ import annotations

import unittest

from support.harness import engine

schedule = engine("claude.schedule")

SEOUL = "Asia/Seoul"
NY = "America/New_York"


def cron(expr, tz=SEOUL):
    return {"cron": expr, "at": None, "timezone": tz}


class Slot(unittest.TestCase):
    def test_daily(self):
        spec = cron("0 3 * * *")
        self.assertEqual(schedule.current_slot(spec, 1794862020), 1794852000)  # 11-17 05:47 → 11-17 03:00
        self.assertEqual(schedule.current_slot(spec, 1794852000), 1794852000)  # exactly 03:00 is that slot
        self.assertEqual(schedule.current_slot(spec, 1794851940), 1794765600)  # 02:59 → the day before
        self.assertEqual(schedule.fire_times(spec, 1794862020, 3), [1794938400, 1795024800, 1795111200])

    def test_weekdays(self):
        spec = cron("30 9 * * 1-5")
        self.assertEqual(schedule.current_slot(spec, 1794870000), 1794789000)  # Tue 11-17 08:00 → Mon 11-16 09:30
        self.assertEqual(schedule.current_slot(spec, 1795230000), 1795134600)  # Sat 11-21 12:00 → Fri 11-20 09:30
        self.assertEqual(schedule.current_slot(spec, 1795393740), 1795134600)  # Mon 11-23 09:29 → Fri 11-20 09:30

    def test_every_quarter_hour(self):
        spec = cron("*/15 * * * *")
        self.assertEqual(schedule.current_slot(spec, 1794877620), 1794877200)  # 10:07 → 10:00
        self.assertEqual(schedule.fire_times(spec, 1794877620, 3), [1794878100, 1794879000, 1794879900])

    def test_day_of_month_or_day_of_week(self):
        spec = cron("0 12 1 * 1")  # the 1st of a month, or a Monday
        self.assertEqual(schedule.current_slot(spec, 1796184000), 1796094000)  # Wed 12-02 13:00 → Tue 12-01 12:00 (the 1st)
        self.assertEqual(schedule.current_slot(spec, 1796702400), 1796612400)  # Tue 12-08 13:00 → Mon 12-07 12:00

    def test_month_end(self):
        spec = cron("0 0 31 * *")
        self.assertEqual(schedule.current_slot(spec, 1794862020), 1793372400)  # November has no 31st → 10-31
        self.assertEqual(schedule.fire_times(spec, 1794862020, 3), [1798642800, 1801321200, 1806418800])

    def test_one_off(self):
        spec = {"cron": None, "at": "2026-11-18T15:00", "timezone": SEOUL}
        self.assertIsNone(schedule.current_slot(spec, 1794978000))  # 14:00, before it
        self.assertEqual(schedule.fire_times(spec, 1794978000, 3), [1794981600])
        self.assertEqual(schedule.current_slot(spec, 1795075260), 1794981600)  # the next day, after it
        self.assertEqual(schedule.fire_times(spec, 1795075260, 3), [])

    def test_wall_time_skipped_by_daylight_saving(self):
        spec = cron("30 2 * * *", NY)  # 2026-03-08 02:30 does not exist in New York
        self.assertEqual(schedule.current_slot(spec, 1772985600), 1772868600)  # 03-08 12:00 → 03-07 02:30
        self.assertEqual(schedule.fire_times(spec, 1772868600, 1), [1773037800])  # then 03-09 02:30

    def test_wall_time_repeated_by_daylight_saving(self):
        spec = cron("30 1 * * *", NY)  # 2026-11-01 01:30 happens twice; it fires once, the first time
        self.assertEqual(schedule.current_slot(spec, 1793552400), 1793511000)
        self.assertEqual(schedule.fire_times(spec, 1793424600, 2), [1793511000, 1793511000 + 86400 + 3600])


class Parse(unittest.TestCase):
    def test_fields(self):
        f = schedule.parse_cron("0,30 9-17/4 */10 1 *")
        self.assertEqual(f["minute"], [0, 30])
        self.assertEqual(f["hour"], [9, 13, 17])
        self.assertEqual(f["day"], [1, 11, 21, 31])
        self.assertEqual(f["month"], [1])
        self.assertIsNone(f["weekday"])
        self.assertEqual(schedule.parse_cron("0 0 * * 1-5")["weekday"], [1, 2, 3, 4, 5])
        self.assertEqual(schedule.parse_cron("0 0 5/10 * *")["day"], [5, 15, 25], "a/n steps from a to the end of the range")
        self.assertEqual(schedule.parse_cron("0 0 * * 7")["weekday"], [0], "7 is Sunday, as 0 is")
        self.assertIsNone(schedule.parse_cron("0 0 * * *")["day"], "an unrestricted field is None")

    def test_refusals(self):
        for expr, why in [
            ("0 3 * *", "five fields"),
            ("0 3 * * MON", "names"),
            ("0 3 * JAN *", "names"),
            ("60 3 * * *", "out of range"),
            ("0 24 * * *", "out of range"),
            ("0 0 0 * *", "out of range"),
            ("*/2 * * * *", "5 minutes"),
            ("0,3 * * * *", "5 minutes"),
            ("0 3 */2 * 1", "day of month and day of week"),
            ("0 3 L * *", "not a number"),
            ("@daily", "five fields"),
        ]:
            with self.assertRaises(schedule.CronError, msg=expr) as cm:
                schedule.parse_cron(expr)
            self.assertIn(why, str(cm.exception), expr)

    def test_five_minutes_across_the_hour(self):
        with self.assertRaises(schedule.CronError):
            schedule.parse_cron("58,1 * * * *")  # 00:58 → 01:01 is 3 minutes
        schedule.parse_cron("55,0 * * * *")  # 00:55 → 01:00 is 5 minutes
        schedule.parse_cron("*/5 * * * *")


if __name__ == "__main__":
    unittest.main()
