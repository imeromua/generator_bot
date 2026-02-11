import logging
from typing import Any

from aiogram.exceptions import TelegramBadRequest

import database.db_api as db

logger = logging.getLogger(__name__)


async def send_single_window(
    bot: Any,
    user_id: int,
    text: str,
    reply_markup=None,
) -> None:
    """Send a message in "single-window" mode.

    If we have a tracked UI message for the user, try to edit it.
    If edit fails, try to delete the old message and send a new one, then update tracking.

    Note: We keep per-user tracking in user_ui table.
    """
    try:
        ui = db.get_ui_message(int(user_id))
    except Exception:
        ui = None

    if ui:
        chat_id, message_id = ui
        # 1) Try to edit existing UI message
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest as e:
            # message is not modified -> OK
            if "message is not modified" in str(e).lower():
                return
        except Exception:
            pass

        # 2) Try to delete old message (best-effort)
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

    # 3) Send new message (fallback)
    try:
        sent = await bot.send_message(chat_id=int(user_id), text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"single_window: failed to send to user_id={user_id}: {e}")
        return

    try:
        db.set_ui_message(int(user_id), int(sent.chat.id), int(sent.message_id))
    except Exception:
        pass
