import asyncio
import logging
from datetime import datetime

import config
from utils.time import now_kiev

# Імпорти частин планувальника
from services.scheduler_parts.morning_brief import maybe_send_morning_brief
from services.scheduler_parts.auto_close import maybe_auto_close_shift
from services.scheduler_parts.stop_reminder import maybe_send_stop_reminder
from services.scheduler_parts.fuel_alert import check_fuel_alert
from services.scheduler_parts.maintenance_alert import check_maintenance_alert  # FIX #25

# Синхронізацію прибрали, бо вона тепер ручна
# from services.google_sync_parts.sync_cycle import sync_cycle

logger = logging.getLogger(__name__)


async def scheduler_loop(bot):
    """Головний цикл планувальника (без авто-синхронізації)."""
    logger.info("⏰ Scheduler запущено")

    # Стани для одноразового виконання задач на добу
    today_str = now_kiev().strftime("%Y-%m-%d")

    # Прапорці виконання
    brief_sent_today = False
    auto_close_done_today = False

    # Константи
    BRIEF_WINDOW = 60 * 60  # 1 година вікно для брифінгу

    while True:
        try:
            now = now_kiev()
            current_date = now.date()
            current_today_str = current_date.strftime("%Y-%m-%d")

            # Скидання прапорців на новий день
            if current_today_str != today_str:
                today_str = current_today_str
                brief_sent_today = False
                auto_close_done_today = False
                logger.info(f"📅 Новий день: {today_str}")

            # Парсинг часу з конфігу (щоб підхоплювати зміни без рестарту)
            try:
                close_time = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
            except Exception:
                logger.warning(
                    f"⚠️ Некоректний WORK_END_TIME='{getattr(config, 'WORK_END_TIME', '')}'. "
                    f"Використовую fallback 20:30"
                )
                close_time = datetime.strptime("20:30", "%H:%M").time()

            # 1. РАНКОВИЙ БРИФІНГ
            brief_sent_today = await maybe_send_morning_brief(
                bot, now, today_str, brief_sent_today, BRIEF_WINDOW
            )

            # 2. АВТО-ЗАКРИТТЯ ЗМІНИ (о WORK_END_TIME)
            auto_close_done_today, skip_rest = await maybe_auto_close_shift(
                bot, now, close_time, auto_close_done_today
            )
            if skip_rest:
                # Якщо відбулося закриття, даємо паузу і йдемо на нове коло
                await asyncio.sleep(60)
                continue

            # Отримуємо стан один раз для наступних перевірок
            # (щоб не смикати БД в кожній функції окремо)
            try:
                import database.db_api as db
                state = db.get_state()
            except Exception:
                state = {}

            # 3. НАГАДУВАННЯ "НАТИСНІТЬ СТОП" (за N хв до кінця)
            await maybe_send_stop_reminder(
                bot, now, current_date, close_time, today_str, state
            )

            # 4. АЛЕРТИ ПО ПАЛИВУ (низький рівень)
            await check_fuel_alert(bot, state)

            # 5. FIX #25: АЛЕРТИ ПО ТО (наближення техобслуговування)
            await check_maintenance_alert(bot, state)

            # --- АВТОМАТИЧНУ СИНХРОНІЗАЦІЮ ВИДАЛЕНО ---
            # Тепер ми покладаємося тільки на БД.
            # Імпорт/Експорт таблиці робиться вручну через адмінку.

        except asyncio.CancelledError:
            logger.info("🛑 Scheduler зупинено")
            break
        except Exception as e:
            logger.error(f"❌ Scheduler Error: {e}", exc_info=True)
            await asyncio.sleep(60)

        # Перевірка кожну хвилину
        await asyncio.sleep(60)
