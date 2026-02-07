import logging
import os

from aiogram import Router, F, types

import config
from keyboards.builders import admin_panel, report_period
from services.excel_report import generate_report

router = Router()
logger = logging.getLogger(__name__)


# --- ЗВІТИ ---
@router.callback_query(F.data == "download_report")
async def report_ask(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("📊 Період:", reply_markup=report_period())


@router.callback_query(F.data.in_({"rep_current", "rep_prev"}))
async def report_gen(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        await cb.message.edit_text("⏳ Генерую звіт, зачекайте...")
        period = "current" if cb.data == "rep_current" else "prev"

        file_path, caption = await generate_report(period)

        if not file_path:
            await cb.message.edit_text(caption, reply_markup=admin_panel())
            return

        file = types.FSInputFile(file_path)

        nav_kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="⚙️ Адмін панель", callback_data="admin_home"),
                types.InlineKeyboardButton(text="🏠 Головне меню", callback_data="home"),
            ]
        ])

        await cb.message.answer_document(file, caption=caption, reply_markup=nav_kb)

        os.remove(file_path)
        logger.info(f"📊 Звіт згенеровано: {period}")

        await cb.message.delete()
        await cb.answer("✅ Звіт готовий!")

    except Exception as e:
        logger.error(f"Помилка генерації звіту: {e}", exc_info=True)
        await cb.message.edit_text(f"❌ Помилка генерації звіту: {str(e)}", reply_markup=admin_panel())
