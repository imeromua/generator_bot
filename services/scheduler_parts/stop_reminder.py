import logging
from datetime import datetime, timedelta, date as dt_date, time as dt_time

import config
import database.db_api as db
from keyboards.builders import back_to_main

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
        close_dt = datetime.combine(current_date, close_time).replace(tzinfo=config.KYIV)
        reminder_dt = close_dt - timedelta(minutes=reminder_min)
    except Exception:
        close_dt = None
        reminder_dt = None

    # Важливо: нагадування потрібне навіть якщо генератор уже OFF, але зміна не закрита.
    active = state.get("active_shift", "none")

    if reminder_dt and close_dt and active != "none":
        sent_date = db.get_state_value("stop_reminder_sent_date", "") or ""

        # Вікно для відправки: один раз на день у проміжку [reminder_dt, close_dt)
        if (reminder_dt <= now < close_dt) and (sent_date != today_str):
            st_time = state.get("start_time", "")
            txt = (
                f"⏰ <b>Нагадування</b>\n\n"
                f"До кінця робочого дня лишилось <b>{reminder_min} хв</b>.\n"
                f"Якщо генератор вже вимкнули — натисніть <b>СТОП</b> в боті, щоб закрити зміну.\n\n"
                f"Активна зміна: <b>{active}</b>\n"
                f"Старт був о: <b>{st_time}</b>"
            )

            kb_home = back_to_main()

            for admin_id in config.ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, txt, reply_markup=kb_home)
                except Exception as e:
                    logger.warning(f"⚠️ STOP reminder: не вдалося надіслати адміну {admin_id}: {e}")

            db.set_state("stop_reminder_sent_date", today_str)
