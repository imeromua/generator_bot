import asyncio
import logging
from datetime import datetime, time

import config
import database.db_api as db

from services.scheduler_parts.auto_close import maybe_auto_close_shift
from services.scheduler_parts.fuel_alert import maybe_send_fuel_alert
from services.scheduler_parts.morning_brief import maybe_send_morning_brief
from services.scheduler_parts.stop_reminder import maybe_send_stop_reminder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scheduler_loop(bot):
    """
    Фоновий процес для автоматичних нагадувань та перевірок.
    - Щоранковий брифінг строго о 07:30 (вікно 2 хв), тільки для юзерів (не адмінів)
    - Авто-закриття зміни о WORK_END_TIME
    - Алерти по паливу (адмінам) + кнопка "Паливо замовлено"
    - Нагадування "натисніть СТОП" за N хв до WORK_END_TIME
    """
    logger.info("⏰ Scheduler запущено")

    brief_sent_today = False
    auto_close_done_today = False
    last_check_date = None

    brief_window_seconds = 120  # 2 хв

    while True:
        try:
            now = datetime.now(config.KYIV)
            current_date = now.date()
            today_str = current_date.strftime("%Y-%m-%d")

            # Скидаємо прапорці на початку нового дня
            if last_check_date != current_date:
                brief_sent_today = False
                auto_close_done_today = False
                last_check_date = current_date
                logger.info(f"📅 Новий день: {current_date}")

            # 1) Ранковий брифінг
            brief_sent_today = await maybe_send_morning_brief(
                bot,
                now,
                today_str,
                brief_sent_today,
                brief_window_seconds,
            )

            # 2) Парсимо WORK_END_TIME (потрібно і для auto-close, і для reminder)
            try:
                close_time = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
            except ValueError:
                logger.error(f"❌ Неправильний формат WORK_END_TIME: {config.WORK_END_TIME}")
                close_time = time(20, 30)

            # 2) Авто-закриття зміни
            auto_close_done_today, skip_rest = await maybe_auto_close_shift(
                bot,
                now,
                close_time,
                auto_close_done_today,
            )
            if skip_rest:
                await asyncio.sleep(60)
                continue

            # 3) Нагадування STOP + 4) Алерти по паливу (працюють з одним state, як і раніше)
            state = db.get_state()

            await maybe_send_stop_reminder(bot, now, current_date, close_time, today_str, state)
            await maybe_send_fuel_alert(bot, now, today_str, state)

        except Exception as e:
            logger.error(f"❌ Scheduler Error: {e}", exc_info=True)

        await asyncio.sleep(60)
