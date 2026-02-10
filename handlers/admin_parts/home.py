import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from handlers.admin_parts.utils import fmt_state_ts
from keyboards.builders import admin_panel

router = Router()
logger = logging.getLogger(__name__)


# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await state.clear()
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")

    # Короткий статус Sheets прямо в хедері адмінки
    sheets_line = ""
    try:
        is_offline = db.sheet_is_offline()
        
        if not is_offline:
            last_ok = fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))
            sheets_line = f"Google Sheets: 🌐 <b>ONLINE</b> (останній OK: {last_ok})"
        else:
            offline_since = fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))
            sheets_line = f"Google Sheets: 🔴 <b>OFFLINE</b> (з {offline_since})"
            
    except Exception as e:
        logger.warning(f"⚠️ Помилка отримання статусу Sheets: {e}")
        sheets_line = "Google Sheets: ❓ <b>Unknown</b>"

    txt = f"⚙️ <b>Адмін Панель</b>\n\n{sheets_line}"
    
    # Використовуємо клавіатуру з builders.py (кнопку треба прибрати там)
    await cb.message.edit_text(text=txt, reply_markup=admin_panel())