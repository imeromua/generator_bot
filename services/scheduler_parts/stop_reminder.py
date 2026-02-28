import logging
from datetime import datetime, timedelta, date as dt_date, time as dt_time

import config
import database.db_api as db
from keyboards.builders import back_to_main
from services.scheduler_parts.notify import send_single_window

logger = logging.getLogger(__name__)


def _get_stop_reminder_minutes() -> int:
    """Returns reminder minutes before end of work day.

    Supports the current env/config name STOP_REMINDER_MIN and keeps backward compatibility
    with the legacy STOP_REMINDER_MIN_BEFORE_END.
    """
    raw = None
    try:
        raw = getattr(config, "STOP_REMINDER_MIN", None)
    except Exception:
        raw = None

    if raw is None:
        try:
            raw = getattr(config, "STOP_REMINDER_MIN_BEFORE_END", None)
        except Exception:
            raw = None

    try:
        return max(1, int(raw if raw is not None else 15))
    except Exception:
        return 15


def _collect_stop_reminder_recipients() -> list[int]:
    """All users who can realistically press STOP + admins.

    STOP requires personnel binding (operator name) in handlers, so we include users with
    personnel mapping and also all admins.
    """
    recipients: set[int] = set()

    # admins
    try:
        for a in config.ADMIN_IDS or []:
            recipients.add(int(a))
    except Exception:
        pass

    # all users with personnel binding
    try:
        for user_id, _full_name, personnel_name in db.get_all_users_with_personnel():
            if personnel_name and str(personnel_name).strip():
                recipients.add(int(user_id))
    except Exception:
        pass

    return sorted(recipients)


async def maybe_send_stop_reminder(
    bot,
    now: datetime,
    current_date: dt_date,
    close_time: dt_time,
    today_str: str,
    state: dict,
):
    reminder_min = _get_stop_reminder_minutes()

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
            # FIX #29: Use correct state key 'last_start_time' instead of 'start_time'
            st_time = state.get("last_start_time", "")

            txt = (
                f"⏰ <b>Нагадування</b>\n\n"
                f"До кінця робочого дня лишилось <b>{reminder_min} хв</b>.\n"
                f"Якщо генератор вже вимкнули — натисніть <b>СТОП</b> в боті, щоб закрити зміну.\n\n"
                f"Активна зміна: <b>{active}</b>\n"
            )

            # Only show start time if available
            if st_time:
                txt += f"Старт був о: <b>{st_time}</b>"

            kb_home = back_to_main()

            recipients = _collect_stop_reminder_recipients()
            if not recipients:
                logger.warning("⚠️ STOP reminder: список отримувачів порожній")

            for user_id in recipients:
                await send_single_window(bot, user_id, txt, reply_markup=kb_home)

            db.set_state("stop_reminder_sent_date", today_str)
