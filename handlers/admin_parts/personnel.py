from aiogram import Router, F, types

import config
import database.db_api as db
from keyboards.builders import admin_panel

router = Router()


@router.callback_query(F.data == "personnel_menu")
async def personnel_menu(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    users = db.get_all_users_with_personnel()
    if not users:
        return await cb.message.edit_text("👥 Немає користувачів у БД.", reply_markup=admin_panel())

    txt = "👥 <b>Персонал → прив'язка користувачів</b>\n\nОберіть користувача:" \
          "\n<i>(натисніть, щоб призначити ПІБ з колонки 'ПЕРСОНАЛ')</i>"

    kb = []
    for uid, full_name, pers in users[:30]:
        label = f"{full_name}"
        if pers:
            label += f" → ✅ {pers}"
        else:
            label += " → ⚠️ не призначено"
        kb.append([types.InlineKeyboardButton(text=label[:60], callback_data=f"pers_user_{uid}")])

    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_user_"))
async def personnel_choose_user(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        uid = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    user = db.get_user(uid)
    if not user:
        return await cb.answer("❌ Користувача не знайдено", show_alert=True)

    current = db.get_personnel_for_user(uid)
    names = db.get_personnel_names()

    if not names:
        txt = (
            f"👤 <b>{user[1]}</b>\n"
            f"🆔 <code>{uid}</code>\n\n"
            f"Поточна прив'язка: <b>{current or '—'}</b>\n\n"
            f"⚠️ Список персоналу ще не завантажений.\n"
            f"Перевірте, що в таблиці заповнена колонка 'ПЕРСОНАЛ' і синхронізація/імпорт працює."
        )
        kb = [[types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")]]
        return await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

    txt = (
        f"👤 <b>{user[1]}</b>\n"
        f"🆔 <code>{uid}</code>\n\n"
        f"Поточна прив'язка: <b>{current or '—'}</b>\n\n"
        f"Оберіть ПІБ (як у колонці 'ПЕРСОНАЛ'):\n"
    )

    kb = []
    for i, name in enumerate(names[:40]):
        kb.append([types.InlineKeyboardButton(text=name, callback_data=f"pers_set_{uid}_{i}")])

    kb.append([types.InlineKeyboardButton(text="🚫 Зняти прив'язку", callback_data=f"pers_clear_{uid}")])
    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_set_"))
async def personnel_set(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        _, _, uid_s, idx_s = cb.data.split("_", 3)
        uid = int(uid_s)
        idx = int(idx_s)
    except Exception:
        return await cb.answer("❌ Помилка призначення", show_alert=True)

    names = db.get_personnel_names()
    if idx < 0 or idx >= len(names):
        return await cb.answer("⚠️ Список персоналу оновився. Відкрийте ще раз.", show_alert=True)

    db.set_personnel_for_user(uid, names[idx])
    await cb.answer("✅ Призначено", show_alert=True)
    await personnel_choose_user(cb)


@router.callback_query(F.data.startswith("pers_clear_"))
async def personnel_clear(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        uid = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка", show_alert=True)

    db.set_personnel_for_user(uid, None)
    await cb.answer("✅ Прив'язку знято", show_alert=True)
    await personnel_choose_user(cb)
