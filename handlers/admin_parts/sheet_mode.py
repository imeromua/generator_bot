from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from datetime import datetime

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name, fmt_state_ts
from keyboards.builders import sheet_mode_kb

router = Router()


@router.callback_query(F.data == "sheet_mode_menu")
async def sheet_mode_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)
    await state.clear()

    is_offline = False
    forced_offline = False

    try:
        is_offline = db.sheet_is_offline()
    except Exception:
        is_offline = False

    try:
        forced_offline = bool(db.sheet_is_forced_offline())
    except Exception:
        forced_offline = False

    last_ok = fmt_state_ts(db.get_state_value("sheet_last_ok_ts", ""))
    first_fail = fmt_state_ts(db.get_state_value("sheet_first_fail_ts", ""))
    offline_since = fmt_state_ts(db.get_state_value("sheet_offline_since_ts", ""))

    if not is_offline:
        status_line = "🌐 <b>ONLINE</b> (OFFLINE вимкнено)"
    else:
        status_line = "🔌 <b>OFFLINE</b> (примусово)" if forced_offline else "🔌 <b>OFFLINE</b> (авто)"

    txt = (
        "🔧 <b>Google Sheets: режим</b>\n\n"
        f"Стан: {status_line}\n"
        f"Останній успішний доступ: <b>{last_ok}</b>\n"
        f"Перша помилка доступу: <b>{first_fail}</b>\n"
        f"OFFLINE з: <b>{offline_since}</b>\n\n"
        "⚠️ Примусовий ONLINE не гарантує доступність Sheets — лише вимикає офлайн-облік як режим."
    )

    await cb.message.edit_text(txt, reply_markup=sheet_mode_kb(is_offline, forced_offline))
    await cb.answer()


@router.callback_query(F.data == "sheet_force_offline")
async def sheet_force_offline(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        db.sheet_force_offline()
    except Exception:
        pass

    # Логуємо адмінську дію (для аудиту в БД/журналі)
    try:
        now = datetime.now(config.KYIV)
        actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
        db.add_log("sheet_force_offline", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    await cb.answer("✅ OFFLINE увімкнено", show_alert=True)
    await sheet_mode_menu(cb, state)


@router.callback_query(F.data == "sheet_force_online")
async def sheet_force_online(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        db.sheet_force_online()
    except Exception:
        pass

    # Логуємо адмінську дію (для аудиту в БД/журналі)
    try:
        now = datetime.now(config.KYIV)
        actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
        db.add_log("sheet_force_online", actor, ts=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    await cb.answer("✅ OFFLINE вимкнено", show_alert=True)
    await sheet_mode_menu(cb, state)
