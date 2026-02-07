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

    # короткий статус Sheets прямо в хедері адмінки
    sheets_line = ""
    try:
        is_offline = db.sheet_is_offline()
        forced_offline = bool(db.sheet_is_forced_offline())
        if not is_offline:
            last_ok = fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))
            sheets_line = f"Google Sheets: 🌐 <b>ONLINE</b> (останній OK: {last_ok})"
        else:
            offline_since = fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))
            mode = "примусово" if forced_offline else "авто"
            sheets_line = f"Google Sheets: 🔌 <b>OFFLINE</b> ({mode}) з {offline_since}"
    except Exception:
        sheets_line = ""

    txt = "⚙️ <b>Адмін Панель</b>"
    if sheets_line:
        txt += f"\n\n{sheets_line}\n➖➖➖➖➖➖"

    await cb.message.edit_text(txt, reply_markup=admin_panel())
