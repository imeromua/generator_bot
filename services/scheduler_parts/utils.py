from __future__ import annotations

from datetime import datetime, timedelta

import config
import database.db_api as db


def schedule_to_ranges(schedule: dict) -> list[tuple[int, int]]:
    """Перетворює schedule{hour->0/1} у список діапазонів (start_h, end_h), де end_h не включно."""
    ranges: list[tuple[int, int]] = []
    start = None
    for h in range(24):
        off = int(schedule.get(h, 0) or 0) == 1
        if off and start is None:
            start = h
        if (not off) and start is not None:
            ranges.append((start, h))
            start = None

    if start is not None:
        ranges.append((start, 24))

    return ranges


def fmt_range(start_h: int, end_h: int) -> str:
    s = f"{start_h:02d}:00"
    e = "24:00" if end_h == 24 else f"{end_h:02d}:00"
    return f"{s} - {e}"


def yesterday_shifts_summary(now: datetime) -> str:
    y = (now - timedelta(days=1)).date()
    y_str = y.strftime("%Y-%m-%d")

    logs = db.get_logs_for_period(y_str, y_str)

    shifts = {"m": {}, "d": {}, "e": {}, "x": {}}

    for event_type, ts, user_name, value, driver_name in logs:
        if event_type in ("m_start", "m_end", "d_start", "d_end", "e_start", "e_end", "x_start", "x_end"):
            code = event_type.split("_")[0]
            act = event_type.split("_")[1]
            try:
                hhmm = ts.split(" ")[1][:5]
            except Exception:
                hhmm = ""
            if code in shifts and hhmm:
                shifts[code][act] = hhmm

    names = {"m": "🌅 Ранок", "d": "☀️ День", "e": "🌙 Вечір", "x": "⚡ Екстра"}

    lines = []
    any_data = False
    for code in ("m", "d", "e", "x"):
        s = shifts[code].get("start")
        e = shifts[code].get("end")

        if s or e:
            any_data = True

        if s and e:
            lines.append(f"{names[code]}: <b>{s}–{e}</b>")
        elif s and not e:
            lines.append(f"{names[code]}: <b>{s}</b> (не закрито)")
        elif (not s) and e:
            lines.append(f"{names[code]}: (є закриття <b>{e}</b>, старт не знайдено)")
        else:
            lines.append(f"{names[code]}: —")

    if not any_data:
        return "—"

    return "\n".join(lines)


def parse_state_dt(value: str) -> datetime | None:
    if not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(value.strip(), fmt)
            return config.KYIV.localize(dt.replace(tzinfo=None))
        except Exception:
            continue

    return None
