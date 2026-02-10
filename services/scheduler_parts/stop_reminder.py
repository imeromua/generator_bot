import logging
from datetime import datetime, timedelta, date as dt_date, time as dt_time

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db

logger = logging.getLogger(__name__)


async def maybe_send_stop_reminder(
    bot,
    now: datetime,
    current_date: dt_date,
    close_time: dt_time,
    today_str: str,
    state: dict,
):
    # === 3. НАГАДУВАННЯ "НАТИСНІТЬ СТОП" ===
    try:
        reminder_min = max(1, int(getattr(config, "STOP_REMINDER_MIN_BEFORE_END", 15)))
    except Exception:
        reminder_min = 15

    try:
        # ВИПРАВЛЕНО: .localize() -> .replace(tzinfo=...)
        close_dt = datetime.combine(current_date, close_time).replace(tzinfo=config.KYIV)
        
        reminder_dt = close_dt - timedelta(minutes=reminder_min)
    except Exception:
        close_dt = None
        reminder_dt = None

    if reminder_dt and close_dt and state.get("status") == "ON":
        sent_date = db.get_state_value("stop_reminder_sent_date", "") or ""
        if (reminder_dt <= now < close_dt) and (sent_date != today_str):
            active = state.get("active_shift", "none")
            st_time = state.get("start_time", "")
            txt = (
                f"⏰ <b>Нагадування</b>\n\n"
                f"До кінця робочого дня лишилось <b>{reminder_min} хв</b>.\n"
                f"Якщо генератор вже вимкнули — натисніть <b>СТОП</b> в боті, щоб закрити зміну.\n\n"
                f"Поточний стан: <b>ON</b>\n"
                f"Активна зміна: <b>{active}</b>\n"
                f"Старт був о: <b>{st_time}</b>"
            )

            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        txt,
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]]
                        ),
                    )
                except Exception as e:
                    logger.warning(f"⚠️ STOP reminder: не вдалося надіслати адміну {admin_id}: {e}")

            db.set_state("stop_reminder_sent_date", today_str)