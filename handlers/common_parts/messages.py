"""FIX #25: Message history viewer.

Обробник для перегляду історії повідомлень (максимум 5).
"""

import logging
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from keyboards.builders import InlineKeyboardBuilder

router = Router()
logger = logging.getLogger(__name__)


def _format_message_time(ts_str: str) -> str:
    """Форматує час повідомлення.

    Args:
        ts_str: Timestamp string in format YYYY-MM-DD HH:MM:SS

    Returns:
        Human-readable relative time string
    """
    if not ts_str:
        return "невідомо"

    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=config.KYIV)
        now = datetime.now(config.KYIV)

        diff = now - dt

        if diff.total_seconds() < 60:
            return "щойно"
        elif diff.total_seconds() < 3600:
            mins = int(diff.total_seconds() // 60)
            return f"{mins} хв тому"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() // 3600)
            return f"{hours} год тому"
        elif dt.date() == (now - timedelta(days=1)).date():
            return f"вчора о {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%d.%m %H:%M")
    except Exception:
        return ts_str[:16] if len(ts_str) >= 16 else ts_str


def _get_message_icon(message_type: str) -> str:
    """Повертає іконку за типом повідомлення.

    Args:
        message_type: Type of message (info, success, warning, error, alert)

    Returns:
        Emoji icon for message type
    """
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "alert": "🔔",
    }
    return icons.get(message_type, "📨")


@router.callback_query(F.data == "view_messages")
async def view_messages(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Показує історію повідомлень.

    Args:
        cb: Callback query
        state: FSM context
    """
    await state.clear()

    user_id = cb.from_user.id
    messages = db.get_user_messages(user_id, limit=5)

    if not messages:
        txt = (
            "📨 <b>Повідомлення</b>\n"
            "──────────────\n\n"
            "🔕 <i>Повідомлень поки немає</i>"
        )
    else:
        txt = (
            f"📨 <b>Повідомлення</b> ({len(messages)}/5)\n"
            "──────────────\n\n"
        )

        for i, (message_text, message_type, timestamp) in enumerate(messages, 1):
            icon = _get_message_icon(message_type)
            time_str = _format_message_time(timestamp)
            txt += f"{icon} {message_text}\n<i>⏰ {time_str}</i>\n\n"

    # Кнопки: Очистити | На головну
    builder = InlineKeyboardBuilder()

    if messages:
        builder.button(text="🗑️ Очистити", callback_data="clear_messages")

    builder.button(text="🏠 Головне меню", callback_data="main_menu")
    builder.adjust(1)

    await cb.message.edit_text(txt, reply_markup=builder.as_markup())
    await cb.answer()


@router.callback_query(F.data == "clear_messages")
async def clear_messages(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Очищає історію повідомлень.

    Args:
        cb: Callback query
        state: FSM context
    """
    await state.clear()

    user_id = cb.from_user.id
    db.clear_user_messages(user_id)

    txt = (
        "📨 <b>Повідомлення</b>\n"
        "──────────────\n\n"
        "✅ <i>Історія повідомлень очищена</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Головне меню", callback_data="main_menu")

    await cb.message.edit_text(txt, reply_markup=builder.as_markup())
    await cb.answer("✅ Повідомлення очищено")
