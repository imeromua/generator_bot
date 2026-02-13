"""Fuel order handler.

Admin handler for confirming fuel order and disabling alerts.
"""

import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name

router = Router()
logger = logging.getLogger(__name__)


# --- ПАЛИВО: замовлено ---
@router.callback_query(F.data == "fuel_ordered")
async def fuel_ordered(cb: types.CallbackQuery) -> None:
    """Handle fuel order confirmation.

    Marks fuel as ordered and disables alerts until next refill.
    Updates state and logs the action.

    Args:
        cb: Callback query
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    today_str = now.strftime("%Y-%m-%d")

    db.set_state("fuel_ordered_date", today_str)
    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    try:
        db.add_log("fuel_ordered", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    # Оновлюємо повідомлення (якщо можемо)
    try:
        orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
        note = "\n\n✅ <b>Паливо замовлено.</b> Нагадування вимкнено до заправки (поки паливо знову не стане ≥ порогу)."
        new_text = (orig + note).strip() if orig else note.strip()

        # прибираємо кнопку, залишаємо лише "На головну" для зручності
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]
        ])

        await cb.message.edit_text(new_text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_ordered edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_ordered edit failed: {e}")

    await cb.answer("✅ Прийнято", show_alert=True)
