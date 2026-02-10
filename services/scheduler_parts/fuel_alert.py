import logging
import asyncio
from datetime import datetime

import config
import database.db_api as db

logger = logging.getLogger(__name__)


async def check_fuel_alert(bot, state: dict):
    """
    Перевіряє рівень палива і надсилає попередження, якщо він низький.
    Викликається з планувальника раз на хвилину.
    """
    # Якщо функція вимкнена в конфігу (поріг 0 або менше)
    if config.FUEL_ALERT_THRESHOLD_L <= 0:
        return

    try:
        current_fuel = float(state.get("current_fuel", 0.0) or 0.0)
    except Exception:
        return

    # Якщо палива достатньо — нічого не робимо
    if current_fuel >= config.FUEL_ALERT_THRESHOLD_L:
        return

    # Перевірка кулдауну (щоб не спамити кожну хвилину)
    last_sent_ts_str = state.get("fuel_alert_last_sent_ts", "")
    
    should_send = True
    now = datetime.now()

    if last_sent_ts_str:
        try:
            last_sent = datetime.strptime(last_sent_ts_str, "%Y-%m-%d %H:%M:%S")
            diff_min = (now - last_sent).total_seconds() / 60.0
            if diff_min < config.FUEL_ALERT_COOLDOWN_MIN:
                should_send = False
        except Exception:
            # Якщо дата побита — краще надіслати, щоб не пропустити
            should_send = True

    if should_send:
        logger.warning(f"⚠️ FUEL ALERT: {current_fuel} L < {config.FUEL_ALERT_THRESHOLD_L} L")
        
        txt = (
            f"⛽ <b>УВАГА! Низький рівень палива</b>\n\n"
            f"Залишок: <b>{current_fuel:.1f} л</b>\n"
            f"Поріг: {config.FUEL_ALERT_THRESHOLD_L} л\n\n"
            f"<i>Заплануйте дозаправку!</i>"
        )

        # Надсилаємо всім адмінам
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, txt)
            except Exception as e:
                logger.error(f"Failed to send fuel alert to {admin_id}: {e}")

        # Оновлюємо час останньої відправки в БД
        db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))