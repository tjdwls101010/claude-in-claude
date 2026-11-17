"""When a schedule fires: a five-field cron in numeric form, or a one-off `at`, in a named time zone (K6). The slot an automatic trigger fills is the latest fire time at or before the moment the job starts its worker (K4·K26).

Wall times follow the zone: a time daylight saving skips does not fire that day, and a time it repeats fires once, the first time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))
MIN_INTERVAL = 300
# How far back or ahead a search for a fire time goes: a Feb 29 schedule fires once in four years.
HORIZON_DAYS = 366 * 8 + 2


class CronError(ValueError):
    """A cron expression this skill does not take, with the reason."""


def _field(text, name, lo, hi):
    """The sorted values of one field, or None for `*`."""
    if text == "*":
        return None
    values = set()
    for item in text.split(","):
        base, _, step = item.partition("/")
        if step:
            if not step.isdigit() or int(step) == 0:
                raise CronError(f"{name} {item!r}: the step after / is not a number above 0")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            x, _, y = base.partition("-")
            if not (x.isdigit() and y.isdigit()):
                raise CronError(f"{name} {item!r} is not a number or range; names such as MON or JAN are not taken")
            a, b = int(x), int(y)
        elif base.isdigit():
            a = b = int(base)
            if step:
                b = hi
        else:
            raise CronError(f"{name} {item!r} is not a number or range; names such as MON or JAN are not taken")
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise CronError(f"{name} {item!r} is out of range {lo}-{hi}")
        values.update(range(a, b + 1, int(step) if step else 1))
    if name == "weekday" and 7 in values:
        values.discard(7)
        values.add(0)
    return sorted(values)


def parse_cron(expr):
    """The fields of a cron expression as sorted value lists (None for `*`): `minute`, `hour`, `day`, `month`, `weekday` (0 is Sunday; 7 is taken as 0). CronError for anything else: not five numeric fields, values out of range, day of month and day of week both restricted when either is a stepped `*`, or fire times less than 5 minutes apart."""
    parts = (expr or "").split()
    if len(parts) != 5:
        raise CronError(f"{expr!r}: a cron expression has five fields (minute hour day-of-month month day-of-week), numbers only")
    fields = {name: _field(text, name, lo, hi) for text, (name, lo, hi) in zip(parts, FIELDS)}
    day_text, weekday_text = parts[2], parts[4]
    if fields["day"] is not None and fields["weekday"] is not None and (day_text.startswith("*") or weekday_text.startswith("*")):
        raise CronError(f"{expr!r}: with both day of month and day of week restricted, a stepped * in either is read differently by cron implementations; list the values")
    gap = _smallest_gap(fields)
    if gap < MIN_INTERVAL:
        raise CronError(f"{expr!r} fires {gap // 60} minute(s) apart; GitHub runs a schedule at most every 5 minutes")
    return fields


def _smallest_gap(fields):
    """The smallest number of seconds between two fire times within a day and across midnight, taking every hour the expression allows as a day's hours."""
    minutes = fields["minute"] if fields["minute"] is not None else list(range(60))
    hours = fields["hour"] if fields["hour"] is not None else list(range(24))
    times = sorted(h * 60 + m for h in hours for m in minutes)
    gaps = [b - a for a, b in zip(times, times[1:])]
    gaps.append(times[0] + 24 * 60 - times[-1])
    return min(gaps) * 60


def _day_matches(fields, d):
    if fields["month"] is not None and d.month not in fields["month"]:
        return False
    weekday = (d.weekday() + 1) % 7  # Monday is 0 in Python, 1 in cron
    day_ok = fields["day"] is None or d.day in fields["day"]
    weekday_ok = fields["weekday"] is None or weekday in fields["weekday"]
    if fields["day"] is not None and fields["weekday"] is not None:
        return day_ok or weekday_ok
    return day_ok and weekday_ok


def _wall(d, hour, minute, tz):
    """The instant a wall time on day `d` names in `tz`, or None when daylight saving skips it; a repeated wall time is its first occurrence."""
    local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz, fold=0)
    back = local.astimezone(timezone.utc).astimezone(tz)
    if (back.year, back.month, back.day, back.hour, back.minute) != (d.year, d.month, d.day, hour, minute):
        return None
    return int(local.timestamp())


def _day_fires(fields, d, tz):
    if not _day_matches(fields, d):
        return []
    minutes = fields["minute"] if fields["minute"] is not None else range(60)
    hours = fields["hour"] if fields["hour"] is not None else range(24)
    out = [_wall(d, h, m, tz) for h in hours for m in minutes]
    return sorted(t for t in out if t is not None)


def _at_instant(spec):
    tz = ZoneInfo(spec["timezone"])
    local = datetime.strptime(spec["at"], "%Y-%m-%dT%H:%M").replace(tzinfo=tz, fold=0)
    return int(local.timestamp())


def current_slot(spec, now):
    """The latest fire time at or before `now` (epoch seconds), or None when there is none — a one-off whose time has not come."""
    if spec.get("at"):
        at = _at_instant(spec)
        return at if at <= now else None
    fields = parse_cron(spec["cron"])
    tz = ZoneInfo(spec["timezone"])
    today = datetime.fromtimestamp(now, tz).date()
    for back in range(HORIZON_DAYS):
        fires = [t for t in _day_fires(fields, today - timedelta(days=back), tz) if t <= now]
        if fires:
            return fires[-1]
    return None


def fire_times(spec, now, count):
    """The next `count` fire times after `now` (epoch seconds); a one-off has its own time while it is ahead and none after."""
    if spec.get("at"):
        at = _at_instant(spec)
        return [at] if at > now else []
    fields = parse_cron(spec["cron"])
    tz = ZoneInfo(spec["timezone"])
    today = datetime.fromtimestamp(now, tz).date()
    out = []
    for ahead in range(HORIZON_DAYS):
        out += [t for t in _day_fires(fields, today + timedelta(days=ahead), tz) if t > now]
        if len(out) >= count:
            break
    return out[:count]
