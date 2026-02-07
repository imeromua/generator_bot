import logging
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from utils.time import format_hours_hhmm

from services.scheduler_parts.utils import parse_state_dt

logger = logging.getLogger(__name__)


async def maybe_send_fuel_alert(bot, now: datetime, today_str: str, state: dict):
    # === 4. АЛЕРТИ ПО ПАЛИВУ (АДМІНАМ) ===
    try:
        fuel_level = float(state.get("current_fuel", 0.0) or 0.0)
    except Exception:
        fuel_level = 0.0

    threshold = float(getattr(config, "FUEL_ALERT_THRESHOLD_L", 40.0) or 40.0)
    cooldown_min = int(getattr(config, "FUEL_ALERT_COOLDOWN_MIN", 60) or 60)

    ordered_date = (db.get_state_value("fuel_ordered_date", "") or "").strip()

    # Якщо паливо відновилось — знімаємо прапорець "замовлено"
    if fuel_level >= threshold and ordered_date:
        db.set_state("fuel_ordered_date", "")

    if fuel_level < threshold and ordered_date != today_str:
        last_sent_raw = (db.get_state_value("fuel_alert_last_sent_ts", "") or "").strip()
        last_sent_dt = parse_state_dt(last_sent_raw)
        can_send = (last_sent_dt is None) or ((now - last_sent_dt) >= timedelta(minutes=cooldown_min))

        if can_send:
            hours_left = fuel_level / config.FUEL_CONSUMPTION if config.FUEL_CONSUMPTION > 0 else 0
            hours_left_hhmm = format_hours_hhmm(hours_left)

            txt = (
                f"⛽ <b>Низький рівень палива</b>\n\n"
                f"Поточний залишок: <b>{fuel_level:.1f} л</b> (поріг: {threshold:.0f} л)\n"
                f"Вистачить на: <b>~{hours_left_hhmm}</b>\n\n"
                f"Якщо паливо вже замовили — натисніть кнопку нижче, і нагадування вимкнеться до заправки."
            )

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Паливо замовлено", callback_data="fuel_ordered")],
                    [InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")],
                ]
            )

            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, txt, reply_markup=kb)
                except Exception as e:
                    logger.warning(f"⚠️ Fuel alert: не вдалося надіслати адміну {admin_id}: {e}")

            db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))
