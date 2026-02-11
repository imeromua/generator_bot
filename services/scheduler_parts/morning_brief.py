import asyncio
import logging
from datetime import datetime, time as dt_time

import config
import database.db_api as db
from utils.time import format_hours_hhmm
from keyboards.builders import back_to_main

from services.scheduler_parts.utils import (
    schedule_to_ranges,
    fmt_range,
    yesterday_shifts_summary,
)

logger = logging.getLogger(__name__)


async def maybe_send_morning_brief(
    bot,
    now: datetime,
    today_str: str,
    brief_sent_today: bool,
    brief_window_seconds: int,
) -> bool:
    """Спроба відправити ранковий брифінг (якщо зараз у вікні відправки)."""
    current_date = now.date()

    try:
        brief_time = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
    except Exception:
        logger.error(
            f"❌ Неправильний формат MORNING_BRIEF_TIME: {getattr(config, 'MORNING_BRIEF_TIME', None)}"
        )
        brief_time = dt_time(7, 30)

    # ВИПРАВЛЕНО: .localize() -> .replace(tzinfo=...)
    target_dt = datetime.combine(current_date, brief_time).replace(tzinfo=config.KYIV)

    diff_s = (now - target_dt).total_seconds()

    # Якщо бот запустили/перезапустили вже після вікна — брифінг за цей день пропускаємо
    if (diff_s >= brief_window_seconds) and (not brief_sent_today):
        brief_sent_today = True

    if (0 <= diff_s < brief_window_seconds) and (not brief_sent_today):
        logger.info(f"📢 Час ранкового брифінгу: {brief_time.strftime('%H:%M')}")

        schedule = db.get_schedule(today_str)
        ranges = schedule_to_ranges(schedule)
        total_off = sum((e - s) for s, e in ranges)

        st = db.get_state()
        try:
            current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
        except Exception:
            current_fuel = 0.0

        hours_left = current_fuel / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
        hours_left_hhmm = format_hours_hhmm(hours_left)

        to_service = config.MAINTENANCE_LIMIT - (st["total_hours"] - st["last_oil"])
        to_service_hhmm = format_hours_hhmm(to_service)

        now_h = now.hour
        now_status = (
            "🔴 Зараз: <b>відключення</b>"
            if int(schedule.get(now_h, 0) or 0) == 1
            else "🟢 Зараз: <b>світло є</b>"
        )

        txt = (
            f"☀️ <b>Ранковий брифінг</b> ({now.strftime('%d.%m.%Y')})\n\n"
            f"📅 <b>Графік відключень (сьогодні)</b>\n"
        )

        if not ranges:
            txt += "✅ Відключень не заплановано.\n"
        else:
            for s, e in ranges:
                txt += f"🔴 {fmt_range(s, e)}\n"
            txt += f"\n⏱ Сумарно без світла: <b>{total_off} год</b>\n"

        txt += f"{now_status}\n\n"

        txt += (
            f"⛽ Паливо (за таблицею): <b>{current_fuel:.1f} л</b>\n"
            f"⏳ Вистачить на: <b>~{hours_left_hhmm}</b>\n"
            f"🛢 До ТО: <b>{to_service_hhmm}</b>\n\n"
        )

        txt += "📌 <b>Вчорашні зміни</b>\n"
        txt += yesterday_shifts_summary(now)
        txt += "\n\n"

        reminders = []
        if current_fuel < config.FUEL_ALERT_THRESHOLD_L:
            reminders.append(f"⚠️ Низький рівень палива: <b>{current_fuel:.1f} л</b>")
        if to_service <= 0:
            reminders.append(f"⚠️ ТО прострочене: <b>{to_service_hhmm}</b>")
        elif to_service < 20:
            reminders.append(f"⏳ До ТО залишилось: <b>{to_service_hhmm}</b>")

        if reminders:
            txt += "🔔 <b>Нагадування</b>\n" + "\n".join(reminders)

        users = db.get_all_users()

        if not users:
            logger.warning("⚠️ Немає користувачів для розсилки")
        else:
            success_count = 0
            fail_count = 0

            kb_home = back_to_main()

            for user_id, user_name in users:
                # Брифінг тільки юзерам (не адмінам)
                if user_id in config.ADMIN_IDS:
                    continue

                try:
                    await bot.send_message(user_id, txt, reply_markup=kb_home)
                    success_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    fail_count += 1
                    logger.warning(f"⚠️ Не вдалося надіслати {user_name} (ID: {user_id}): {e}")

            logger.info(f"✅ Брифінг надіслано: {success_count} успішно, {fail_count} помилок")

        brief_sent_today = True

    return brief_sent_today
