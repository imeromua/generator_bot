import logging

from aiogram import Router, types

import config
from keyboards.builders import admin_panel

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(lambda cb: cb.data == "download_report")
async def report_removed(cb: types.CallbackQuery):
    # Feature removed: keep handler only to avoid crashes if old button/callback arrives.
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("ℹ️ Функцію формування Excel-звітів видалено.", reply_markup=admin_panel())
