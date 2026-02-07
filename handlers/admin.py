from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime
import logging

import config
import database.db_api as db
from handlers.admin_parts.drivers import router as drivers_router
from handlers.admin_parts.export_logs import router as export_logs_router
from handlers.admin_parts.maintenance import router as maintenance_router
from handlers.admin_parts.personnel import router as personnel_router
from handlers.admin_parts.reports import router as reports_router
from handlers.admin_parts.schedule import router as schedule_router
from handlers.admin_parts.sheet_mode import router as sheet_mode_router
from handlers.admin_parts.utils import (
    actor_name as _actor_name,
    fmt_state_ts as _fmt_state_ts,
)
from keyboards.builders import admin_panel

router = Router()
router.include_router(sheet_mode_router)
router.include_router(export_logs_router)
router.include_router(personnel_router)
router.include_router(schedule_router)
router.include_router(maintenance_router)
router.include_router(reports_router)
router.include_router(drivers_router)

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
            last_ok = _fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))
            sheets_line = f"Google Sheets: 🌐 <b>ONLINE</b> (останній OK: {last_ok})"
        else:
            offline_since = _fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))
            mode = "примусово" if forced_offline else "авто"
            sheets_line = f"Google Sheets: 🔌 <b>OFFLINE</b> ({mode}) з {offline_since}"
    except Exception:
        sheets_line = ""

    txt = "⚙️ <b>Адмін Панель</b>"
    if sheets_line:
        txt += f"\n\n{sheets_line}\n➖➖➖➖➖➖"

    await cb.message.edit_text(txt, reply_markup=admin_panel())


# --- ПАЛИВО: замовлено ---
@router.callback_query(F.data == "fuel_ordered")
async def fuel_ordered(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    now = datetime.now(config.KYIV)
    today_str = now.strftime("%Y-%m-%d")

    db.set_state("fuel_ordered_date", today_str)
    db.set_state("fuel_alert_last_sent_ts", now.strftime("%Y-%m-%d %H:%M:%S"))

    actor = _actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    try:
        db.add_log("fuel_ordered", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    # Оновлюємо повідомлення (якщо можемо)
    try:
        orig = getattr(cb.message, "html_text", None) or getattr(cb.message, "text", "") or ""
        note = "\n\n✅ <b>Паливо замовлено.</b> Нагадування вимкнено до заправки (поки паливо знову не стане ≥ порогу)."
        new_text = (orig + note).strip() if orig else note.strip()

        # прибираємо кнопку, залишаємо лише "На головну" для зручності
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🏠 Дашборд", callback_data="home")]
        ])

        await cb.message.edit_text(new_text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"fuel_ordered edit failed: {e}")
    except Exception as e:
        logger.warning(f"fuel_ordered edit failed: {e}")

    await cb.answer("✅ Прийнято", show_alert=True)


# --- ЮЗЕРИ ---
@router.callback_query(F.data == "users_list")
async def users_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    users = db.get_all_users()
    txt = "👥 <b>Користувачі в БД:</b>\n\n"

    if not users:
        txt += "<i>Поки немає зареєстрованих користувачів</i>"
    else:
        for uid, name in users:
            txt += f"👤 {name}\n🆔 <code>{uid}</code>\n\n"
        txt += "<i>Натисніть на ID, щоб скопіювати.</i>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")]])
    await cb.message.edit_text(txt, reply_markup=kb)
