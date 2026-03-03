"""Task 6: Fuel order monitoring.

Monitors fuel level and triggers an automatic fuel order suggestion when the
level drops below the fixed threshold. Sends an actionable Telegram message
to admins with inline buttons.
"""

import logging

import config
import database.db_api as db
import database.api.fuel_orders as fo_api
from utils.time import now_kiev

logger = logging.getLogger(__name__)

# Threshold (litres) — fixed order threshold
THRESHOLD_ORDER = 80.0

# Debounce: minimum hours between repeat order suggestions
_SUGGESTION_COOLDOWN_H = 4
_DEBOUNCE_STATE_KEY = "fuel_order_suggestion_last_ts"

# Recommended order amount (litres)
RECOMMENDED_ORDER_L = 200.0


def _is_debounced(now) -> bool:
    from datetime import datetime
    ts_str = db.get_state_value(_DEBOUNCE_STATE_KEY, "") or ""
    if not ts_str:
        return False
    try:
        last = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        if last.tzinfo is None:
            last = last.replace(tzinfo=config.KYIV)
        diff_h = (now - last).total_seconds() / 3600.0
        return diff_h < _SUGGESTION_COOLDOWN_H
    except Exception:
        return False


def _estimate_days_remaining(current_fuel: float) -> float:
    """Estimate days of fuel remaining based on recent consumption stats."""
    try:
        stats = fo_api.get_fuel_consumption_stats(days=7)
        rate = stats.get("avg_rate_per_hour", 0.0)
        if rate and rate > 0:
            daily_consumption = rate * 8
            return current_fuel / daily_consumption
    except Exception:
        pass
    return current_fuel / 10.0 if current_fuel > 0 else 0.0


async def check_fuel_order(bot, state: dict) -> None:
    """Check if fuel order should be suggested and send Telegram alert.

    Called from the scheduler loop every minute.
    """
    try:
        current_fuel = float(state.get("current_fuel", 0.0) or 0.0)
    except Exception:
        return

    now = now_kiev()

    if current_fuel > THRESHOLD_ORDER:
        return

    # Already have a pending order? Skip.
    try:
        pending = fo_api.get_orders(status="pending", limit=1)
        ordered = fo_api.get_orders(status="ordered", limit=1)
        confirmed = fo_api.get_orders(status="confirmed", limit=1)
        if pending or ordered or confirmed:
            return
    except Exception:
        pass

    if _is_debounced(now):
        return

    days_remaining = _estimate_days_remaining(current_fuel)
    logger.info(f"⛽ Fuel order suggestion triggered: {current_fuel:.1f}L left, threshold={THRESHOLD_ORDER:.0f}L")

    txt = (
        f"⛽ <b>Час замовити паливо!</b>\n\n"
        f"📊 Залишок: <b>{current_fuel:.1f} л</b>\n"
        f"⏳ Вистачить на: ~{days_remaining:.0f} дн.\n"
        f"📅 Рекомендація: {RECOMMENDED_ORDER_L:.0f} л\n\n"
        f"<i>Поріг: {THRESHOLD_ORDER:.0f} л</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Замовлено", callback_data="fuel_order:create:200"),
                InlineKeyboardButton(text="⏸ Відкласти", callback_data="fuel_order:skip"),
            ]
        ]
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=int(admin_id),
                text=txt,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Failed to send fuel order suggestion to admin {admin_id}: {e}")

    db.set_state(_DEBOUNCE_STATE_KEY, now.strftime("%Y-%m-%d %H:%M:%S"))
