"""FIX #25: Maintenance alerts for generator service time.

Алерти про наближення часу техобслуговування (ТО).
"""

import logging

import config
import database.db_api as db
from database.api.maintenance import get_maintenance_stats
from keyboards.builders import back_to_main
from services.scheduler_parts.notify import send_single_window
from utils.time import now_kiev, format_hours_hhmm
from utils.messaging import notify_all_users  # FIX #25

logger = logging.getLogger(__name__)

# Пороги для алертів (в годинах)
MAINTENANCE_ALERT_THRESHOLDS = [5, 10, 20]  # Алерти при 5, 10, 20 годинах до ТО
MAINTENANCE_ALERT_COOLDOWN_MIN = 60  # Кулдаун 1 година між алертами


async def check_maintenance_alert(bot, state: dict):
    """Перевіряє чи наближається час ТО і надсилає алерти.

    Викликається з планувальника раз на хвилину.
    Алерти надсилаються тільки адмінам.
    """
    try:
        stats = get_maintenance_stats()
        hours_to_service = min(
            float(stats['oil_needed'] or 9999.0),
            float(stats['spark_needed'] or 9999.0),
            float(stats['maintenance_needed'] or 9999.0),
        )
    except Exception:
        return

    if hours_to_service > max(MAINTENANCE_ALERT_THRESHOLDS):
        # Ще далеко до ТО
        return

    # Визначаємо який поріг досягнуто
    triggered_threshold = None
    for threshold in sorted(MAINTENANCE_ALERT_THRESHOLDS):
        if hours_to_service <= threshold:
            triggered_threshold = threshold
            break

    if triggered_threshold is None:
        return

    # Перевіряємо кулдаун
    last_sent_ts_str = db.get_state_value("maintenance_alert_last_sent_ts", "") or ""
    last_threshold_str = db.get_state_value("maintenance_alert_last_threshold", "") or "0"

    should_send = True
    now = now_kiev()

    try:
        last_threshold = int(last_threshold_str)
    except Exception:
        last_threshold = 0

    # Надсилаємо тільки якщо:
    # 1. Поріг змінився (наближаємось до ТО)
    # 2. Або минув кулдаун
    if triggered_threshold == last_threshold:
        # Той же поріг - перевіряємо кулдаун
        if last_sent_ts_str:
            try:
                from datetime import datetime

                last_sent = datetime.strptime(last_sent_ts_str, "%Y-%m-%d %H:%M:%S")
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=config.KYIV)

                diff_min = (now - last_sent).total_seconds() / 60.0
                if diff_min < MAINTENANCE_ALERT_COOLDOWN_MIN:
                    should_send = False
            except Exception as e:
                logger.warning(f"⚠️ Помилка парсингу останнього алерту ТО: {e}")
                should_send = True

    if not should_send:
        return

    # Форматуємо повідомлення
    hours_str = format_hours_hhmm(hours_to_service)

    # Визначаємо рівень терміновості
    if hours_to_service <= 5:
        urgency = "🔴 КРИТИЧНО"
        emoji = "🔴"
    elif hours_to_service <= 10:
        urgency = "🟠 ТЕРМІНОВО"
        emoji = "🟠"
    else:
        urgency = "🟡 ПОПЕРЕДЖЕННЯ"
        emoji = "🟡"

    logger.warning(f"{emoji} АЛЕРТ ТО: {hours_to_service:.1f} год до ТО ({urgency})")

    txt = (
        f"🛠 <b>{urgency}: ЧАС ТЕХОБСЛУГОВУВАННЯ!</b>\n\n"
        f"Залишок до ТО: <b>{hours_str}</b>\n"
        f"Ліміт: {config.MAINTENANCE_LIMIT} год\n\n"
        f"🔧 <i>Заплануйте техобслуговування!</i>"
    )

    kb_home = back_to_main()

    # Надсилаємо адмінам
    for admin_id in config.ADMIN_IDS:
        await send_single_window(bot, int(admin_id), txt, reply_markup=kb_home)

    # FIX #25: Save alert to message history (only for admins)
    notify_all_users(f"🔔 Час ТО: {hours_str} ({urgency})", "alert", admin_only=True)

    # Зберігаємо час та поріг
    db.set_state("maintenance_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))
    db.set_state("maintenance_alert_last_threshold", str(triggered_threshold))
