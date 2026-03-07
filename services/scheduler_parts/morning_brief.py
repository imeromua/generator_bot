import asyncio
import logging
from datetime import datetime, time as dt_time

import config
import database.db_api as db
from database.api.maintenance import get_maintenance_stats
from utils.time import format_hours_hhmm
from keyboards.builders import back_to_main

from services.scheduler_parts.utils import (
    schedule_to_ranges,
    fmt_range,
    yesterday_shifts_summary,
)
from services.scheduler_parts.notify import send_single_window

logger = logging.getLogger(__name__)

# DB state key used to persist the last date the morning brief was sent.
# This prevents double-sends on restart and enables cross-restart idempotency.
_BRIEF_SENT_DATE_KEY = "morning_brief_sent_date"

# Hours-remaining threshold at which a maintenance item appears in the Reminders section.
# Oil and spark warnings fire earlier (closer to service) than planned maintenance because
# planned service typically requires more advance coordination (parts procurement, scheduling).
_OIL_SPARK_WARN_HOURS = 10
_PLANNED_MAINT_WARN_HOURS = 20


def _build_brief_text(now: datetime, today_str: str) -> str:
    """Build the morning briefing message text.

    Assembles a concise but informative operational digest including:
    - Current power status and today's outage schedule
    - Active generator and its status
    - Current fuel level and estimated runtime
    - Separate maintenance countdowns (oil, spark plugs, planned service)
    - Critical warnings (overdue items)
    - Yesterday's shift summary
    """
    # --- Power schedule ---
    schedule = db.get_schedule(today_str)
    if not schedule or not isinstance(schedule, dict):
        logger.warning("⚠️ Графік недоступний або порожній, використовуємо порожній графік")
        schedule = {}

    ranges = schedule_to_ranges(schedule)
    total_off = sum((e - s) for s, e in ranges)

    now_h = now.hour
    is_outage_now = int(schedule.get(now_h, 0) or 0) == 1
    now_status = "🔴 Зараз: <b>відключення</b>" if is_outage_now else "🟢 Зараз: <b>світло є</b>"

    # --- Generator state ---
    st = db.get_state()
    gen_status = str(st.get("status", "OFF") or "OFF").upper()

    try:
        active_gen = db.get_active_generator()
    except Exception:
        active_gen = "main"

    gen_label = "🔋 Основний" if active_gen == "main" else "⚠️ Аварійний"
    gen_on_label = "ON" if gen_status == "ON" else "OFF"

    # --- Fuel ---
    try:
        current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
    except Exception:
        current_fuel = 0.0

    # Use per-generator consumption rate
    if active_gen == "emergency":
        fuel_rate = config.EMERGENCY_FUEL_CONSUMPTION
    else:
        fuel_rate = config.FUEL_CONSUMPTION

    hours_left = current_fuel / fuel_rate if fuel_rate > 0 else 0
    hours_left_hhmm = format_hours_hhmm(hours_left)

    # --- Maintenance stats (separate countdowns for oil, spark, planned service) ---
    # Use None as sentinel when stats are unavailable so we don't show misleading "full interval" values.
    oil_needed: float | None = None
    spark_needed: float | None = None
    maintenance_needed: float | None = None
    try:
        maint = get_maintenance_stats(active_gen)
        oil_needed = float(maint.get("oil_needed") or 0.0)
        spark_needed = float(maint.get("spark_needed") or 0.0)
        maintenance_needed = float(maint.get("maintenance_needed") or 0.0)
    except Exception as e:
        logger.warning(f"⚠️ Помилка читання статистики ТО: {e}")
        # Leave as None — will display "N/A" below rather than a potentially wrong interval value.

    # --- Compose message ---
    txt = f"☀️ <b>Ранковий брифінг</b> ({now.strftime('%d.%m.%Y')})\n\n"

    # Power status
    txt += f"📅 <b>Графік відключень (сьогодні)</b>\n"
    if not ranges:
        txt += "✅ Відключень не заплановано.\n"
    else:
        for s, e in ranges:
            txt += f"🔴 {fmt_range(s, e)}\n"
        txt += f"\n⏱ Сумарно без світла: <b>{total_off} год</b>\n"
    txt += f"{now_status}\n\n"

    # Generator status
    txt += f"⚙️ <b>Генератор</b>\n"
    txt += f"  Активний: {gen_label} ({gen_on_label})\n\n"

    # Fuel
    txt += (
        f"⛽ <b>Паливо</b>\n"
        f"  Залишок: <b>{current_fuel:.1f} л</b>\n"
        f"  Вистачить на: <b>~{hours_left_hhmm}</b>\n\n"
    )

    # Maintenance countdowns (separate per type)
    txt += f"🔧 <b>Техобслуговування</b>\n"
    txt += f"  🛢 До заміни мастила: <b>{format_hours_hhmm(oil_needed) if oil_needed is not None else 'N/A'}</b>\n"
    txt += f"  🔩 До заміни свічок: <b>{format_hours_hhmm(spark_needed) if spark_needed is not None else 'N/A'}</b>\n"
    txt += f"  📋 До планового ТО: <b>{format_hours_hhmm(maintenance_needed) if maintenance_needed is not None else 'N/A'}</b>\n\n"

    # Yesterday's shifts
    txt += "📌 <b>Вчорашні зміни</b>\n"
    txt += yesterday_shifts_summary(now)
    txt += "\n\n"

    # Critical warnings / reminders
    reminders = []
    if current_fuel < config.FUEL_ALERT_THRESHOLD_L:
        reminders.append(f"⚠️ Низький рівень палива: <b>{current_fuel:.1f} л</b>")
    if oil_needed is not None:
        if oil_needed <= 0:
            reminders.append("⚠️ Заміна мастила <b>прострочена!</b>")
        elif oil_needed < _OIL_SPARK_WARN_HOURS:
            reminders.append(f"⏳ До заміни мастила: <b>{format_hours_hhmm(oil_needed)}</b>")
    if spark_needed is not None:
        if spark_needed <= 0:
            reminders.append("⚠️ Заміна свічок <b>прострочена!</b>")
        elif spark_needed < _OIL_SPARK_WARN_HOURS:
            reminders.append(f"⏳ До заміни свічок: <b>{format_hours_hhmm(spark_needed)}</b>")
    if maintenance_needed is not None:
        if maintenance_needed <= 0:
            reminders.append("⚠️ Планове ТО <b>прострочено!</b>")
        elif maintenance_needed < _PLANNED_MAINT_WARN_HOURS:
            reminders.append(f"⏳ До планового ТО: <b>{format_hours_hhmm(maintenance_needed)}</b>")

    if reminders:
        txt += "🔔 <b>Нагадування</b>\n" + "\n".join(reminders)

    return txt


async def maybe_send_morning_brief(
    bot,
    now: datetime,
    today_str: str,
    brief_sent_today: bool,
    brief_window_seconds: int,
) -> bool:
    """Attempt to send the morning briefing (if within the send window).

    Uses a DB-persisted sent date so that restarts within the same day
    do not cause double-sends or missed sends:
    - If the bot restarts AFTER the brief was already sent today, the DB key
      prevents a resend.
    - If the bot restarts BEFORE the window, the brief will be sent when the
      window opens (in-memory flag starts False, DB key has yesterday's date).
    - If the bot restarts AFTER the window but the brief was NOT sent (e.g. bot
      was down the whole window), the window is marked as passed and the brief
      is recorded as missed for that day — same as the old behaviour, but now
      logged explicitly.

    NOTE: Admins are NOT excluded from the morning briefing.  The briefing is
    an operational digest that is equally relevant for admins.
    """
    current_date = now.date()

    try:
        brief_time = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
    except Exception:
        logger.error(f"❌ Неправильний формат MORNING_BRIEF_TIME: {getattr(config, 'MORNING_BRIEF_TIME', None)}")
        brief_time = dt_time(7, 30)

    target_dt = datetime.combine(current_date, brief_time).replace(tzinfo=config.KYIV)
    diff_s = (now - target_dt).total_seconds()

    # Sync in-memory flag from DB (handles cross-restart idempotency)
    if not brief_sent_today:
        try:
            stored_date = db.get_state_value(_BRIEF_SENT_DATE_KEY, "") or ""
            if stored_date == today_str:
                brief_sent_today = True
                logger.debug(f"📋 Morning brief already sent today ({today_str}), skipping")
        except Exception as e:
            logger.warning(f"⚠️ Could not read morning brief sent state: {e}")

    # Mark as "window passed" once we're past it — prevents spurious late sends
    if (diff_s >= brief_window_seconds) and (not brief_sent_today):
        logger.info(
            f"⏭ Morning brief window passed without send "
            f"(diff={diff_s:.0f}s, window={brief_window_seconds}s). "
            f"Bot was likely down during the window."
        )
        brief_sent_today = True

    # Send if within window and not yet sent today
    if (0 <= diff_s < brief_window_seconds) and (not brief_sent_today):
        logger.info(f"📢 Час ранкового брифінгу: {brief_time.strftime('%H:%M')}")

        try:
            txt = _build_brief_text(now, today_str)
        except Exception as e:
            logger.error(f"❌ Failed to build morning brief text: {e}", exc_info=True)
            txt = f"☀️ <b>Ранковий брифінг</b> ({now.strftime('%d.%m.%Y')})\n\n⚠️ Помилка формування брифінгу."

        users = db.get_all_users()

        if not users:
            logger.warning("⚠️ Немає користувачів для розсилки")
        else:
            success_count = 0
            fail_count = 0
            kb_home = back_to_main()

            for user_id, user_name in users:
                # NOTE: admins are NOT excluded — they need the operational digest too.
                try:
                    await send_single_window(bot, int(user_id), txt, reply_markup=kb_home)
                    success_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    fail_count += 1
                    logger.warning(f"⚠️ Не вдалося надіслати {user_name} (ID: {user_id}): {e}")

            logger.info(f"✅ Брифінг надіслано: {success_count} успішно, {fail_count} помилок")

        # Persist sent state to DB so restarts don't resend
        try:
            db.set_state(_BRIEF_SENT_DATE_KEY, today_str)
        except Exception as e:
            logger.warning(f"⚠️ Could not persist morning brief sent state: {e}")

        brief_sent_today = True

    return brief_sent_today
