"""Task 5: Extended notification checks with debouncing and preference support.

Checks critical and important notification conditions and sends alerts to users
who have the relevant notification type enabled.  Enforces a 15-minute debounce
per (user_id, notification_type) key using the generator_state table as a
lightweight cache.
"""

import logging
from datetime import datetime

import config
import database.db_api as db
from database.api.notifications import (
    NOTIFICATION_TYPES,
    get_user_preferences,
    is_notification_enabled,
    get_quiet_hours,
)
from utils.time import now_kiev

logger = logging.getLogger(__name__)

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
    """Return True if current time falls within the user's quiet hours."""
    start_str, end_str = get_quiet_hours(user_id)
    if not start_str or not end_str:
        return False
    try:
        current_time = now.strftime("%H:%M")
        return start_str <= current_time < end_str
    except Exception:
        return False


def _should_notify(user_id: int, notification_type: str, now) -> bool:
    """Check debounce + quiet hours + user preference."""
    if not is_notification_enabled(user_id, notification_type):
        return False
    # Critical notifications ignore quiet hours
    meta = NOTIFICATION_TYPES.get(notification_type, {})
    if meta.get("category") != "critical" and _is_quiet_time(user_id, now):
        return False
    return not _is_debounced(user_id, notification_type, now)


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
        total_hours = float(state.get("total_hours", 0.0) or 0.0)
        last_oil = float(state.get("last_oil_change", 0.0) or 0.0)
        hours_to_service = config.MAINTENANCE_LIMIT - (total_hours - last_oil)
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

    # --- 5. Info: daily_report at 09:00 → all registered users ---
    if now.hour == 9 and now.minute == 0:
        for uid in all_user_ids:
            if _should_notify(uid, "daily_report", now):
                await _notify_user(
                    bot,
                    uid,
                    f"📊 <b>Щоденний звіт</b>\n\n"
                    f"Стан генератора: <b>{gen_status}</b>\n"
                    f"Рівень палива: <b>{current_fuel:.1f} л</b>",
                )
                _mark_sent(uid, "daily_report", now)

    # --- 6. Info: weekly_report on Monday at 09:00 → all registered users ---
    if now.weekday() == 0 and now.hour == 9 and now.minute == 0:
        for uid in all_user_ids:
            if _should_notify(uid, "weekly_report", now):
                await _notify_user(
                    bot,
                    uid,
                    f"📈 <b>Тижневий звіт</b>\n\n"
                    f"Новий тиждень розпочато. Стан генератора: <b>{gen_status}</b>",
                )
                _mark_sent(uid, "weekly_report", now)
