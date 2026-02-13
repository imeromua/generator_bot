"""Schedule viewer handler.

Display today's power outage schedule for users.
"""

from aiogram import Router, F, types

import database.db_api as db
from handlers.common import show_dash
from handlers.user_parts.utils import ensure_user
from utils.time import now_kiev


router = Router()


def _schedule_to_ranges(schedule: dict) -> list[tuple[int, int]]:
    """Convert hourly schedule dict to time ranges.

    Args:
        schedule: Dict with hour -> outage flag (1=outage, 0=power)

    Returns:
        List of (start_hour, end_hour) tuples
    """
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


def _fmt_range(start_h: int, end_h: int) -> str:
    """Format hour range as time string.

    Args:
        start_h: Start hour (0-23)
        end_h: End hour (1-24)

    Returns:
        Formatted string like "08:00 - 12:00"
    """
    s = f"{start_h:02d}:00"
    e = "24:00" if end_h == 24 else f"{end_h:02d}:00"
    return f"{s} - {e}"


@router.callback_query(F.data == "schedule_today")
async def schedule_today(cb: types.CallbackQuery) -> None:
    """Display today's power outage schedule.

    Args:
        cb: Callback query
    """
    now = now_kiev()
    today_str = now.strftime("%Y-%m-%d")
    schedule = db.get_schedule(today_str)

    ranges = _schedule_to_ranges(schedule)
    total_off = sum((e - s) for s, e in ranges)

    now_status = "🔴 Зараз: <b>відключення</b>" if int(schedule.get(now.hour, 0) or 0) == 1 else "🟢 Зараз: <b>світло є</b>"

    banner = f"📅 <b>Графік відключень на сьогодні</b> ({now.strftime('%d.%m.%Y')})\n\n"

    if not ranges:
        banner += "✅ Відключень не заплановано.\n\n"
    else:
        for s, e in ranges:
            banner += f"🔴 {_fmt_range(s, e)}\n"
        banner += f"\n⏱ Сумарно без світла: <b>{total_off} год</b>\n\n"

    banner += now_status

    user = ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    await show_dash(cb.message, user[0], user[1], banner=banner)
    await cb.answer()
