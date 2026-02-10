import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from keyboards.builders import admin_panel

router = Router()
logger = logging.getLogger(__name__)


def _get_status_emoji(is_offline: bool) -> str:
    return "🔴 Offline" if is_offline else "✅ Online"


# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    
    await state.clear()
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")

    # 1. Отримуємо актуальний стан з БД
    st = db.get_state()
    
    # --- СТАТУС ГЕНЕРАТОРА ---
    status = st.get("status", "OFF")
    if status == "ON":
        active_shift = st.get("active_shift", "невідомо")
        # Прибираємо зайве з назви зміни (наприклад m_start -> m)
        shift_code = active_shift.split("_")[0].upper() if "_" in active_shift else active_shift.upper()
        status_line = f"🟢 <b>ПРАЦЮЄ</b> (Зміна: {shift_code})"
    else:
        status_line = "⚪ <b>ВИМКНЕНО</b>"

    # --- ПАЛИВО ---
    try:
        current_fuel = float(st.get("current_fuel", 0.0) or 0.0)
    except ValueError:
        current_fuel = 0.0
    
    fuel_line = f"⛽ Паливо: <b>{current_fuel:.1f} л</b>"

    # --- СЕРВІС (ТО) ---
    try:
        total_hours = float(st.get("total_hours", 0.0) or 0.0)
        last_oil = float(st.get("last_oil_change", 0.0) or 0.0)
        limit = config.MAINTENANCE_LIMIT
        left_hours = limit - (total_hours - last_oil)
    except ValueError:
        left_hours = 0.0

    # Іконка уваги, якщо до ТО мало часу
    if left_hours < 0:
        mnt_icon = "💀 <b>ПРОСТРОЧЕНО!</b>"
    elif left_hours < 20:
        mnt_icon = "⚠️"
    else:
        mnt_icon = "🔧"
    
    mnt_line = f"{mnt_icon} До ТО: <b>{left_hours:.1f} год</b>"

    # --- СТАТУС ТАБЛИЦІ (Міні) ---
    try:
        is_sheet_offline = db.sheet_is_offline()
        sheet_status = _get_status_emoji(is_sheet_offline)
    except Exception:
        sheet_status = "❓ Unknown"

    # Формуємо підсумковий текст
    txt = (
        f"⚙️ <b>Адмін Панель</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}\n"
        f"{fuel_line}\n"
        f"{mnt_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    
    # Використовуємо клавіатуру з builders.py
    await cb.message.edit_text(text=txt, reply_markup=admin_panel())