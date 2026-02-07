import logging

from aiogram import Router, F, types

import config
import database.db_api as db
from keyboards.builders import sync_menu, back_to_admin
from services.sheets_export import full_export
from services.sheets_import import full_import

router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = (
        "🔄 <b>Синхронізація з Google Sheets</b>\n\n"
        "📥 <b>Імпорт</b> — читає дані з Sheets і перезаписує в БД\n"
        "📤 <b>Експорт</b> — записує дані з БД у Sheets (A-AC + вкладка ПОДІЇ)\n\n"
        "⚠️ Імпорт повністю очищає БД перед завантаженням!\n"
    )
    await cb.message.edit_text(txt, reply_markup=sync_menu())
    await cb.answer()


@router.callback_query(F.data == "sync_import")
async def sync_import(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⚙️ Імпорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Імпорт з Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
        full_import()
        
        txt = (
            "✅ <b>Імпорт завершено!</b>\n\n"
            "📄 Дані з Sheets завантажені в БД:\n"
            "• Основна вкладка (A-AC)\n"
            "• Вкладка ПОДІЇ (опціонально)\n\n"
            "⚠️ Старі дані БД було видалено."
        )
        await cb.message.edit_text(txt, reply_markup=back_to_admin())

    except Exception as e:
        logger.error(f"❌ Помилка імпорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка імпорту</b>\n\n{e}",
            reply_markup=back_to_admin()
        )


@router.callback_query(F.data == "sync_export")
async def sync_export(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⚙️ Експорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Експорт в Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
        full_export()
        
        txt = (
            "✅ <b>Експорт завершено!</b>\n\n"
            "📄 Дані з БД записані в Sheets:\n"
            "• Основна вкладка (A-AC)\n"
            "• Вкладка ПОДІЇ (всі логи)\n"
        )
        await cb.message.edit_text(txt, reply_markup=back_to_admin())

    except Exception as e:
        logger.error(f"❌ Помилка експорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка експорту</b>\n\n{e}",
            reply_markup=back_to_admin()
        )
