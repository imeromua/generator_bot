import logging
from datetime import datetime

import config
import database.db_api as db
from keyboards.builders import back_to_main
from services.scheduler_parts.notify import send_single_window

logger = logging.getLogger(__name__)


async def check_fuel_alert(bot, state: dict):
    """Перевіряє рівень палива і надсилає попередження, якщо він низький.

    Викликається з планувальника раз на хвилину.
    Кулдаун береться з config.FUEL_ALERT_COOLDOWN_MIN.

    IMPORTANT: Uses "single-window" delivery (edit/replace last UI message) to avoid chat spam.
    """
    if config.FUEL_ALERT_THRESHOLD_L <= 0:
        return

    try:
        current_fuel = float(state.get("current_fuel", 0.0) or 0.0)
    except Exception:
        return

    if current_fuel >= config.FUEL_ALERT_THRESHOLD_L:
        return

    last_sent_ts_str = db.get_state_value("fuel_alert_last_sent_ts", "") or ""

    should_send = True
    now = datetime.now()

    if last_sent_ts_str:
        try:
            last_sent = datetime.strptime(last_sent_ts_str, "%Y-%m-%d %H:%M:%S")
            diff_min = (now - last_sent).total_seconds() / 60.0
            if diff_min < config.FUEL_ALERT_COOLDOWN_MIN:
                should_send = False
        except Exception:
            should_send = True

    if not should_send:
        return

    logger.warning(f"⚠️ FUEL ALERT: {current_fuel} L < {config.FUEL_ALERT_THRESHOLD_L} L")

    txt = (
        f"⛽ <b>УВАГА! Низький рівень палива</b>\n\n"
        f"Залишок: <b>{current_fuel:.1f} л</b>\n"
        f"Поріг: {config.FUEL_ALERT_THRESHOLD_L} л\n\n"
        f"<i>Заплануйте дозаправку!</i>"
    )

    kb_home = back_to_main()

    for admin_id in config.ADMIN_IDS:
        await send_single_window(bot, int(admin_id), txt, reply_markup=kb_home)

    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))
