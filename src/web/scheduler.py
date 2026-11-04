"""Small local scheduler for workflow runs."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/Los_Angeles"


def compute_next_run(kind: str, expression: str, timezone_name: str = DEFAULT_TIMEZONE, now=None):
    """Compute the next UTC ISO run time for an interval or simple cron schedule."""
    now = now or datetime.now(timezone.utc)
    if kind == "interval":
        seconds = parse_interval_seconds(expression)
        return (now + timedelta(seconds=seconds)).isoformat()
    if kind == "cron":
        return next_cron_time(expression, timezone_name, now).isoformat()
    raise ValueError("schedule kind must be 'interval' or 'cron'")


def parse_interval_seconds(expression: str) -> int:
    expression = str(expression).strip().lower()
    if expression.isdigit():
        return max(1, int(expression))
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    suffix = expression[-1:]
    if suffix in units and expression[:-1].isdigit():
        return max(1, int(expression[:-1]) * units[suffix])
    raise ValueError("interval expression must be seconds or a value like 5m, 2h, 1d")


def next_cron_time(expression: str, timezone_name: str, now_utc):
    """Return next matching time for a simple five-field cron expression."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must have five fields: minute hour day month weekday")
    tz = ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    local = now_utc.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if cron_matches(fields, local):
            return local.astimezone(timezone.utc)
        local += timedelta(minutes=1)
    raise ValueError("cron expression did not match within one year")


def cron_matches(fields, dt):
    minute, hour, day, month, weekday = fields
    cron_weekday = (dt.weekday() + 1) % 7
    return (
        field_matches(minute, dt.minute, 0, 59)
        and field_matches(hour, dt.hour, 0, 23)
        and field_matches(day, dt.day, 1, 31)
        and field_matches(month, dt.month, 1, 12)
        and field_matches(weekday, cron_weekday, 0, 6)
        and dt.day <= calendar.monthrange(dt.year, dt.month)[1]
    )


def field_matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if part.startswith("*/") and part[2:].isdigit():
            step = int(part[2:])
            if step > 0 and (value - minimum) % step == 0:
                return True
        elif "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit() and int(start) <= value <= int(end):
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False
