from dataclasses import dataclass
from datetime import datetime, timedelta

MONTHS = {name: i + 1 for i, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}
WEEKDAYS = {name: i for i, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}


class CronError(ValueError):
    pass


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    dom_any: bool
    dow_any: bool


def _num(token: str, names: dict[str, int], field: str) -> int:
    low = token.lower()
    if low in names:
        return names[low]
    if token.isdigit():
        return int(token)
    raise CronError(f"bad cron field {field!r}")


def _parse_part(part: str, lo: int, hi: int, names: dict[str, int], field: str) -> set[int]:
    step = 1
    if "/" in part:
        part, step_s = part.split("/", 1)
        if not step_s.isdigit() or int(step_s) <= 0:
            raise CronError(f"bad cron field {field!r}")
        step = int(step_s)
    if part == "*":
        start, end = lo, hi
    elif "-" in part:
        a, b = part.split("-", 1)
        start, end = _num(a, names, field), _num(b, names, field)
    else:
        start = _num(part, names, field)
        end = hi if step > 1 else start
    if start < lo or end > hi or start > end:
        raise CronError(f"bad cron field {field!r}")
    return set(range(start, end + 1, step))


def _parse_field(field: str, lo: int, hi: int, names: dict[str, int]) -> tuple[frozenset[int], bool]:
    if field == "*":
        return frozenset(range(lo, hi + 1)), True
    values: set[int] = set()
    for part in field.split(","):
        values.update(_parse_part(part, lo, hi, names, field))
    return frozenset(values), False


def parse(expr: str) -> CronSpec:
    parts = expr.split()
    if len(parts) != 5:
        raise CronError(f"expected 5 cron fields, got {len(parts)}")
    minute_f, hour_f, dom_f, month_f, dow_f = parts
    minutes, _ = _parse_field(minute_f, 0, 59, {})
    hours, _ = _parse_field(hour_f, 0, 23, {})
    days, dom_any = _parse_field(dom_f, 1, 31, {})
    months, _ = _parse_field(month_f, 1, 12, MONTHS)
    weekdays, dow_any = _parse_field(dow_f, 0, 7, WEEKDAYS)
    weekdays = frozenset(0 if w == 7 else w for w in weekdays)
    return CronSpec(minutes, hours, days, months, weekdays, dom_any, dow_any)


def _next_month(dt: datetime) -> datetime:
    year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_matches(spec: CronSpec, dt: datetime) -> bool:
    dom_match = dt.day in spec.days
    dow_match = (dt.weekday() + 1) % 7 in spec.weekdays
    if spec.dom_any and spec.dow_any:
        return True
    if spec.dom_any:
        return dow_match
    if spec.dow_any:
        return dom_match
    return dom_match or dow_match


def next_after(spec: CronSpec, dt: datetime) -> datetime:
    cur = (dt + timedelta(minutes=1)).replace(second=0, microsecond=0)
    deadline = dt + timedelta(days=366)
    while cur <= deadline:
        if cur.month not in spec.months:
            cur = _next_month(cur)
        elif not _day_matches(spec, cur):
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif cur.hour not in spec.hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        elif cur.minute not in spec.minutes:
            cur = cur + timedelta(minutes=1)
        else:
            return cur
    raise CronError("no run in the next year")
