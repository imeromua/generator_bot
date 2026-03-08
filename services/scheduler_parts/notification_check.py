"""Extended notification checks with debouncing, preference support, and daily report.

Checks critical and important notification conditions and sends alerts to users
who have the relevant notification type enabled.  Enforces a 15-minute debounce
per (user_id, notification_type) key using the generator_state table as a
lightweight cache.

The daily report is handled separately: it fires once per day at
config.MORNING_BRIEF_TIME using a DB key for cross-restart idempotency.
"""

import logging
from datetime import datetime, time as dt_time

import config
import database.db_api as db
from database.api.maintenance import get_maintenance_stats
from database.api.notifications import (
    NOTIFICATION_TYPES,
    get_user_preferences,
    is_notification_enabled,
    get_quiet_hours,
)
from utils.time import now_kiev, format_hours_hhmm
from services.scheduler_parts.utils import (
    schedule_to_ranges,
    fmt_range,
    yesterday_shifts_summary,
)

logger = logging.getLogger(__name__)

# DB state key used to persist the last date the daily report was sent.
# Prevents double-sends on restart and enables cross-restart idempotency.
DAILY_REPORT_KEY = "daily_report_sent_date"

# Hours-remaining threshold at which a maintenance item appears in the Reminders section.
_OIL_SPARK_WARN_HOURS = 10
_PLANNED_MAINT_WARN_HOURS = 20

# Debounce: minimum minutes between repeat notifications of the same type per user
DEBOUNCE_MINUTES = 15

# Key prefix in generator_state used for debounce timestamps
_DEBOUNCE_KEY_PREFIX = "notif_debounce_"


def _debounce_key(user_id: int, notification_type: str) -> str:
    return f"{_DEBOUNCE_KEY_PREFIX}{user_id}_{notification_type}"


def _is_debounced(user_id: int, notification_type: str, now) -> bool:
    key = _debounce_key(user_id, notification_type)
    ts_str = db.get_state_value(key, "") or ""
    if not ts_str:
        return False
    try:
        last = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        if last.tzinfo is None:
            last = last.replace(tzinfo=config.KYIV)
        diff_min = (now - last).total_seconds() / 60.0
        return diff_min < DEBOUNCE_MINUTES
    except Exception:
        return False


def _mark_sent(user_id: int, notification_type: str, now) -> None:
    key = _debounce_key(user_id, notification_type)
    db.set_state(key, now.strftime("%Y-%m-%d %H:%M:%S"))


def _is_quiet_time(user_id: int, now) -> bool:
    """Return True if current time falls within the user's quiet hours.

    Correctly handles overnight ranges (e.g. 22:00-08:00) by detecting when
    start > end and splitting the comparison accordingly.
    """
    start_str, end_str = get_quiet_hours(user_id)
    if not start_str or not end_str:
        return False
    try:
        current_time = now.strftime("%H:%M")
        if start_str <= end_str:
            # Normal range: e.g. 08:00 - 20:00
            return start_str <= current_time < end_str
        else:
            # Overnight range: e.g. 22:00 - 08:00
            # Active when current >= start (evening) OR current < end (early morning)
            return current_time >= start_str or current_time < end_str
    except Exception:
        return False


def _should_notify(user_id: int, notification_type: str, now) -> bool:
    """Check debounce + quiet hours + user preference.

    Logs the reason when a notification is suppressed so operators can
    diagnose why a message was not delivered.
    """
    if not is_notification_enabled(user_id, notification_type):
        logger.debug(
            "🔕 Notification suppressed: user=%s type=%s reason=preference_disabled",
            user_id,
            notification_type,
        )
        return False
    # Critical notifications ignore quiet hours
    meta = NOTIFICATION_TYPES.get(notification_type, {})
    if meta.get("category") != "critical" and _is_quiet_time(user_id, now):
        logger.debug(
            "🌙 Notification suppressed: user=%s type=%s reason=quiet_hours",
            user_id,
            notification_type,
        )
        return False
    if _is_debounced(user_id, notification_type, now):
        logger.debug(
            "⏱ Notification suppressed: user=%s type=%s reason=debounce",
            user_id,
            notification_type,
        )
        return False
    return True


async def _notify_user(bot, user_id: int, text: str, reply_markup=None) -> None:
    """Send a notification message to a user (new message, not single-window)."""
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Failed to send notification to user {user_id}: {e}")


def _get_all_user_ids() -> list[int]:
    """Return all registered user IDs."""
    try:
        rows = db.get_all_users()
        return [r[0] for r in rows]
    except Exception:
        return []


def _build_daily_report_text(now: datetime, today_str: str) -> str:
    """Build the daily report message text.

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

    # --- Compose message ---
    txt = f"📊 <b>Щоденний звіт</b> ({now.strftime('%d.%m.%Y')})\n\n"

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


async def check_all_notifications(bot, state: dict) -> None:
    """Run all notification condition checks.

    Called from the scheduler loop every minute.
    """
    now = now_kiev()
    admin_ids = [int(x) for x in config.ADMIN_IDS]
    all_user_ids = _get_all_user_ids()

    try:
        current_fuel = float(state.get("current_fuel", 0.0) or 0.0)
    except Exception:
        current_fuel = 0.0

    try:
        stats = get_maintenance_stats()
        hours_to_service = min(
            float(stats['oil_needed'] or 9999.0),
            float(stats['spark_needed'] or 9999.0),
            float(stats['maintenance_needed'] or 9999.0),
        )
    except Exception:
        hours_to_service = 9999.0

    gen_status = state.get("status", "OFF")
    last_start_str = state.get("last_start_time", "") or ""

    # --- 1. Critical: fuel < 15L ---
    if current_fuel < 15:
        for uid in admin_ids:
            if _should_notify(uid, "fuel_critical", now):
                await _notify_user(
                    bot,
                    uid,
                    f"🔴 <b>КРИТИЧНО: Паливо закінчується!</b>\n\n"
                    f"Залишок: <b>{current_fuel:.1f} л</b>\n"
                    f"⚠️ Необхідне негайне поповнення!",
                )
                _mark_sent(uid, "fuel_critical", now)

    # --- 2. Important: fuel < 40L (for users who enabled it) ---
    if current_fuel < 40:
        for uid in admin_ids:
            if _should_notify(uid, "fuel_warning", now):
                await _notify_user(
                    bot,
                    uid,
                    f"⚠️ <b>Увага: Низький рівень палива</b>\n\n"
                    f"Залишок: <b>{current_fuel:.1f} л</b>\n"
                    f"Рекомендується замовити паливо.",
                )
                _mark_sent(uid, "fuel_warning", now)

    # --- 3. Critical: shift > 9 hours ---
    if gen_status == "ON" and last_start_str:
        try:
            last_start_date = state.get("last_start_date", "") or ""
            if last_start_date:
                start_dt = datetime.strptime(f"{last_start_date} {last_start_str}", "%Y-%m-%d %H:%M")
                start_dt = start_dt.replace(tzinfo=config.KYIV)
                shift_hours = (now - start_dt).total_seconds() / 3600.0
                if shift_hours > 9:
                    for uid in admin_ids:
                        if _should_notify(uid, "long_shift", now):
                            await _notify_user(
                                bot,
                                uid,
                                f"🛑 <b>Зміна триває {shift_hours:.1f} год!</b>\n\n"
                                f"Можливо, забули зупинити зміну?\n"
                                f"Запущено о {last_start_str}",
                            )
                            _mark_sent(uid, "long_shift", now)
        except Exception:
            pass

    # --- 4. Important: maintenance soon (< 10 hours) ---
    if hours_to_service < 10:
        for uid in admin_ids:
            if _should_notify(uid, "maintenance_soon", now):
                await _notify_user(
                    bot,
                    uid,
                    f"🔧 <b>Час техобслуговування!</b>\n\n"
                    f"Залишок до ТО: <b>{hours_to_service:.1f} год</b>\n"
                    f"Заплануйте техобслуговування.",
                )
                _mark_sent(uid, "maintenance_soon", now)

    # --- 5. Info: daily_report at MORNING_BRIEF_TIME → all registered users (once per day) ---
    # Uses DB key for idempotency — fires exactly once regardless of restarts.
    try:
        brief_time = datetime.strptime(config.MORNING_BRIEF_TIME, "%H:%M").time()
    except Exception:
        brief_time = dt_time(8, 0)

    target_dt = datetime.combine(now.date(), brief_time).replace(tzinfo=config.KYIV)
    diff_s = (now - target_dt).total_seconds()

    if 0 <= diff_s < 3600:
        today_str = now.strftime("%Y-%m-%d")
        sent_date = db.get_state_value(DAILY_REPORT_KEY, "") or ""
        if sent_date != today_str:
            try:
                txt = _build_daily_report_text(now, today_str)
            except Exception as e:
                logger.error(f"❌ Failed to build daily report text: {e}", exc_info=True)
                txt = f"📊 <b>Щоденний звіт</b> ({now.strftime('%d.%m.%Y')})\n\n⚠️ Помилка формування звіту."
            for uid in all_user_ids:
                await _notify_user(bot, uid, txt)
            db.set_state(DAILY_REPORT_KEY, today_str)
            logger.info(f"✅ Щоденний звіт надіслано {len(all_user_ids)} користувач(ам)")

    # --- 6. Info: weekly_report on Monday at 09:xx → all registered users ---
    # Use a full-hour window (any minute in hour 9 on Monday) — debounce prevents double-sends.
    if now.weekday() == 0 and now.hour == 9:
        for uid in all_user_ids:
            if _should_notify(uid, "weekly_report", now):
                await _notify_user(
                    bot,
                    uid,
                    f"📈 <b>Тижневий звіт</b>\n\n"
                    f"Новий тиждень розпочато. Стан генератора: <b>{gen_status}</b>",
                )
                _mark_sent(uid, "weekly_report", now)
