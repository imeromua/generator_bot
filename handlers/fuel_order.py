"""Callback handlers for fuel order inline buttons.

Handles:
  fuel_order:create:<amount>  — admin confirms fuel has been ordered
  fuel_order:skip             — admin postpones the suggestion (resets debounce)
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

import database.db_api as db
from utils.time import now_kiev

logger = logging.getLogger(__name__)
router = Router()

# Must match the key in fuel_order_check.py
_DEBOUNCE_STATE_KEY = "fuel_order_suggestion_last_ts"


@router.callback_query(F.data.startswith("fuel_order:create"))
async def on_fuel_ordered(callback: CallbackQuery) -> None:
    """Admin confirmed that fuel has been ordered."""
    try:
        amount = float(callback.data.split(":")[-1])
    except (IndexError, ValueError):
        amount = 200.0

    try:
        import database.api.fuel_orders as fo_api
        fo_api.create_order(amount=amount, created_by=callback.from_user.id)
    except Exception as e:
        logger.warning(f"Could not save fuel order record: {e}")

    # Clear debounce so scheduler won't re-send until next threshold breach
    db.set_state(_DEBOUNCE_STATE_KEY, "")

    await callback.message.edit_text(
        f"✅ <b>Замовлення палива підтверджено!</b>\n"
        f"Замовлено: {amount:.0f} л",
        parse_mode="HTML",
    )
    await callback.answer("Замовлення зафіксовано")


@router.callback_query(F.data == "fuel_order:skip")
async def on_fuel_postponed(callback: CallbackQuery) -> None:
    """Admin postponed the fuel order. Resets debounce for 4 hours."""
    now = now_kiev()
    db.set_state(_DEBOUNCE_STATE_KEY, now.strftime("%Y-%m-%d %H:%M:%S"))

    await callback.message.edit_text(
        "⏸ <b>Замовлення відкладено.</b>\n"
        "<i>Нагадування через 4 години.</i>",
        parse_mode="HTML",
    )
    await callback.answer("Відкладено")
