import asyncio
import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database.db_api as db
from keyboards.builders import sync_menu, back_to_admin
from services.sheets_export import full_export
from services.sheets_import import full_import

router = Router()
logger = logging.getLogger(__name__)


def _logs_title() -> str:
    return (getattr(config, "LOGS_SHEET_NAME", None) or "ПОДІЇ").strip() or "ПОДІЇ"


def _import_confirm_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="✅ Підтверджую імпорт", callback_data="sync_import_execute")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="sync_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "sync_menu")
async def show_sync_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    logs_title = _logs_title()

    txt = (
        "🔄 <b>Синхронізація з Google Sheets</b>\n\n"
        "📥 <b>Імпорт</b> — читає дані з Sheets і перезаписує в БД\n"
        "📤 <b>Експорт</b> — записує дані з БД у Sheets (A-AC + вкладка журналу)\n\n"
        f"🗂 Вкладка журналу подій: <b>{logs_title}</b>\n\n"
        "⚠️ Імпорт повністю очищає БД перед завантаженням (потрібне підтвердження).\n"
    )
    await cb.message.edit_text(txt, reply_markup=sync_menu())
    await cb.answer()


@router.callback_query(F.data == "sync_import")
async def sync_import_confirm(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # Safety guard: не імпортуємо, якщо генератор "ON" (може йти зміна прямо зараз)
    try:
        st = db.get_state() or {}
        if (st.get("status") or "OFF") == "ON":
            return await cb.answer("⛔ Спочатку закрийте активну зміну (генератор ON)", show_alert=True)
    except Exception:
        pass

    txt = (
        "⚠️ <b>Підтвердження імпорту</b>\n\n"
        "Імпорт зробить наступне:\n"
        "• Повністю очистить БД\n"
        "• Завантажить дані з Google Sheets\n\n"
        "❌ <b>Цю операцію НЕМОЖЛИВО ВІДМІНИТИ!</b>\n\n"
        "Рекомендація: перед імпортом зробіть експорт як резервну копію." 
    )

    await cb.message.edit_text(txt, reply_markup=_import_confirm_kb())
    await cb.answer()


@router.callback_query(F.data == "sync_import_execute")
async def sync_import_execute(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⚙️ Імпорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Імпорт з Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
        await asyncio.to_thread(full_import)

        logs_title = _logs_title()
        txt = (
            "✅ <b>Імпорт завершено!</b>\n\n"
            "📄 Дані з Sheets завантажені в БД:\n"
            "• Основна вкладка (A-AC)\n"
            f"• Вкладка {logs_title} (опціонально)\n\n"
            "⚠️ Старі дані БД було видалено."
        )
        await cb.message.edit_text(txt, reply_markup=back_to_admin())

    except Exception as e:
        logger.error(f"❌ Помилка імпорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка імпорту</b>\n\n{e}",
            reply_markup=back_to_admin(),
        )


@router.callback_query(F.data == "sync_export")
async def sync_export(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.answer("⚙️ Експорт запускається...", show_alert=False)
    await cb.message.edit_text("⏳ <b>Експорт в Google Sheets...</b>\n\nЗачекайте, це може зайняти кілька секунд...")

    try:
        await asyncio.to_thread(full_export)

        logs_title = _logs_title()
        txt = (
            "✅ <b>Експорт завершено!</b>\n\n"
            "📄 Дані з БД записані в Sheets:\n"
            "• Основна вкладка (A-AC)\n"
            f"• Вкладка {logs_title} (всі логи)\n"
        )
        await cb.message.edit_text(txt, reply_markup=back_to_admin())

    except Exception as e:
        logger.error(f"❌ Помилка експорту: {e}", exc_info=True)
        await cb.message.edit_text(
            f"❌ <b>Помилка експорту</b>\n\n{e}",
            reply_markup=back_to_admin(),
        )
