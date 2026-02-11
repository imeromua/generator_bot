import logging
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

import config
import database.db_api as db
from keyboards.builders import admin_panel

router = Router()
logger = logging.getLogger(__name__)


def _is_outdated_ui(cb: types.CallbackQuery) -> bool:
    """Повертає True, якщо callback прийшов зі старого повідомлення (не з відстежуваного single-window UI)."""
    try:
        ui = db.get_ui_message(int(cb.from_user.id))
    except Exception:
        ui = None

    if not ui:
        return False

    _chat_id, message_id = ui
    try:
        return int(cb.message.message_id) != int(message_id)
    except Exception:
        return False


# --- ВХІД В АДМІНКУ ---
@router.callback_query(F.data == "admin_home")
async def adm_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    # Якщо натиснули кнопку на старому повідомленні — прибираємо його
    if _is_outdated_ui(cb):
        try:
            await cb.message.delete()
        except Exception:
            pass
        return await cb.answer("✅ Оновлено (відкрийте адмінку з актуального меню)")

    await state.clear()
    logger.info(f"👤 Адмін {cb.from_user.id} відкрив панель")

    # 1. Отримуємо актуальний стан з БД
    st = db.get_state()

    # --- СТАТУС ГЕНЕРАТОРА ---
    status = st.get("status", "OFF")
    if status == "ON":
        active_shift = st.get("active_shift", "невідомо")
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

    if left_hours < 0:
        mnt_icon = "💀 <b>ПРОСТРОЧЕНО!</b>"
    elif left_hours < 20:
        mnt_icon = "⚠️"
    else:
        mnt_icon = "🔧"

    mnt_line = f"{mnt_icon} До ТО: <b>{left_hours:.1f} год</b>"

    # REMOVED: Sheet offline status - not relevant for manual sync workflow (SHEETS_RUNTIME_ENABLED=0)
    # Admin uses manual import/export commands instead

    txt = (
        f"⚙️ <b>Адмін Панель</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}\n"
        f"{fuel_line}\n"
        f"{mnt_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    await cb.message.edit_text(text=txt, reply_markup=admin_panel())

    # Фіксуємо message_id як єдине вікно для адміна
    try:
        db.set_ui_message(int(cb.from_user.id), int(cb.message.chat.id), int(cb.message.message_id))
    except Exception:
        pass
