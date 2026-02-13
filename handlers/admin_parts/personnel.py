"""Personnel management handler.

Complete personnel directory management:
- Personnel list (CRUD)
- User bindings to personnel names
- Sync with Google Sheets personnel column
"""

import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name
from keyboards.builders import admin_panel, back_to_admin, after_add_menu

router = Router()
logger = logging.getLogger(__name__)


class AddPersonnelForm(StatesGroup):
    """FSM states for adding personnel."""
    name = State()


class EditPersonnelForm(StatesGroup):
    """FSM states for editing personnel."""
    old_name = State()
    new_name = State()


# --- ПЕРСОНАЛ: ГОЛОВНЕ МЕНЮ ---
@router.callback_query(F.data == "personnel_menu")
async def personnel_menu(cb: types.CallbackQuery) -> None:
    """Display personnel management menu.

    Args:
        cb: Callback query
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = "👥 <b>Управління персоналом</b>\n\nОберіть дію:"

    kb = [
        [types.InlineKeyboardButton(text="🔗 Прив'язка користувачів", callback_data="personnel_assign")],
        [types.InlineKeyboardButton(text="📝 Список персоналу", callback_data="personnel_list")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- ПРИВ'ЯЗКА КОРИСТУВАЧІВ ---
@router.callback_query(F.data == "personnel_assign")
async def personnel_assign(cb: types.CallbackQuery) -> None:
    """Display user list for personnel binding.

    Args:
        cb: Callback query
    """
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

    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_user_"))
async def personnel_choose_user(cb: types.CallbackQuery) -> None:
    """Display personnel selection for specific user.

    Args:
        cb: Callback query with format "pers_user_UID"
    """
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
        kb = [
            [types.InlineKeyboardButton(text="➕ Додати персонал", callback_data="add_personnel_start")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_assign")],
        ]
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
    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_assign")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("pers_set_"))
async def personnel_set(cb: types.CallbackQuery) -> None:
    """Bind personnel name to user.

    Args:
        cb: Callback query with format "pers_set_UID_INDEX"
    """
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

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    logger.info(f"👥 {actor} призначив {names[idx]} для user_id={uid}")

    await cb.answer("✅ Призначено", show_alert=True)
    await personnel_choose_user(cb)


@router.callback_query(F.data.startswith("pers_clear_"))
async def personnel_clear(cb: types.CallbackQuery) -> None:
    """Clear personnel binding from user.

    Args:
        cb: Callback query with format "pers_clear_UID"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        uid = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка", show_alert=True)

    db.set_personnel_for_user(uid, None)

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)
    logger.info(f"👥 {actor} зняв прив'язку для user_id={uid}")

    await cb.answer("✅ Прив'язку знято", show_alert=True)
    await personnel_choose_user(cb)


# --- СПИСОК ПЕРСОНАЛУ ---
@router.callback_query(F.data == "personnel_list")
async def personnel_list(cb: types.CallbackQuery) -> None:
    """Display complete personnel list.

    Args:
        cb: Callback query
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    personnel = db.get_personnel_names()

    if not personnel:
        txt = "👥 <b>Список персоналу</b>\n\n⚠️ Список пустий.\n\n<i>Додайте персонал або запустіть синхронізацію.</i>"
        kb = [
            [types.InlineKeyboardButton(text="➕ Додати персонал", callback_data="add_personnel_start")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")],
        ]
        return await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

    txt = f"👥 <b>Список персоналу</b> ({len(personnel)})\n\nОберіть ПІБ для редагування або видалення:"

    kb = []
    for idx, name in enumerate(personnel[:40]):
        kb.append([types.InlineKeyboardButton(
            text=f"👤 {name}",
            callback_data=f"personnel_manage_{idx}"
        )])

    kb.append([types.InlineKeyboardButton(text="➕ Додати персонал", callback_data="add_personnel_start")])
    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_menu")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- УПРАВЛІННЯ ПЕРСОНАЛОМ ---
@router.callback_query(F.data.startswith("personnel_manage_"))
async def personnel_manage(cb: types.CallbackQuery) -> None:
    """Display management options for personnel entry.

    Args:
        cb: Callback query with format "personnel_manage_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    personnel = db.get_personnel_names()
    if idx < 0 or idx >= len(personnel):
        await cb.answer("⚠️ Список оновився. Поверніться.", show_alert=True)
        return await personnel_list(cb)

    name = personnel[idx]

    txt = f"👤 <b>Персонал: {name}</b>\n\nОберіть дію:"

    kb = [
        [types.InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"personnel_edit_{idx}")],
        [types.InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"personnel_delete_{idx}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="personnel_list")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- ДОДАТИ ПЕРСОНАЛ ---
@router.callback_query(F.data == "add_personnel_start")
async def personnel_add(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Start personnel addition process.

    Args:
        cb: Callback query
        state: FSM context
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("✍️ Введіть ПІБ (прізвище та ім'я):", reply_markup=back_to_admin())
    await state.set_state(AddPersonnelForm.name)


@router.message(AddPersonnelForm.name)
async def personnel_save(msg: types.Message, state: FSMContext) -> None:
    """Save new personnel entry.

    Args:
        msg: Message with personnel name
        state: FSM context
    """
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    name = msg.text.strip()

    if not name:
        return await msg.answer("❌ ПІБ не може бути порожнім", reply_markup=back_to_admin())

    if len(name) > 50:
        return await msg.answer("❌ ПІБ занадто довгий (максимум 50 символів)", reply_markup=back_to_admin())

    success = db.add_personnel_name(name)

    actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)

    if success:
        logger.info(f"👥 {actor} додав персонал: {name}")
        await msg.answer(f"✅ {name} доданий.", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Персонал {name} вже існує.", reply_markup=after_add_menu())

    await state.clear()


# --- РЕДАГУВАТИ ПЕРСОНАЛ ---
@router.callback_query(F.data.startswith("personnel_edit_"))
async def personnel_edit_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Start personnel edit process.

    Args:
        cb: Callback query with format "personnel_edit_INDEX"
        state: FSM context
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    personnel = db.get_personnel_names()
    if idx < 0 or idx >= len(personnel):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await personnel_list(cb)

    old_name = personnel[idx]

    await state.update_data(old_name=old_name)
    await state.set_state(EditPersonnelForm.new_name)

    txt = f"✏️ <b>Редагування персоналу</b>\n\nПоточне ПІБ: <b>{old_name}</b>\n\nВведіть нове ПІБ:"

    await cb.message.edit_text(txt, reply_markup=back_to_admin())


@router.message(EditPersonnelForm.new_name)
async def personnel_edit_save(msg: types.Message, state: FSMContext) -> None:
    """Save edited personnel name.

    Args:
        msg: Message with new personnel name
        state: FSM context
    """
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    data = await state.get_data()
    old_name = data.get("old_name")

    if not old_name:
        await state.clear()
        return await msg.answer("❌ Помилка: втрачено стан", reply_markup=back_to_admin())

    new_name = msg.text.strip()

    if not new_name:
        return await msg.answer("❌ ПІБ не може бути порожнім", reply_markup=back_to_admin())

    if len(new_name) > 50:
        return await msg.answer("❌ ПІБ занадто довгий (максимум 50 символів)", reply_markup=back_to_admin())

    success = db.update_personnel_name(old_name, new_name)

    actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)

    if success:
        logger.info(f"👥 {actor} змінив персонал: {old_name} → {new_name}")
        await msg.answer(f"✅ Змінено: {old_name} → {new_name}", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Персонал {new_name} вже існує або помилка оновлення.", reply_markup=after_add_menu())

    await state.clear()


# --- ВИДАЛИТИ ПЕРСОНАЛ ---
@router.callback_query(F.data.startswith("personnel_delete_"))
async def personnel_delete_confirm(cb: types.CallbackQuery) -> None:
    """Show personnel deletion confirmation.

    Args:
        cb: Callback query with format "personnel_delete_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    personnel = db.get_personnel_names()
    if idx < 0 or idx >= len(personnel):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await personnel_list(cb)

    name = personnel[idx]

    txt = f"⚠️ <b>Підтвердження видалення</b>\n\nВи впевнені, що хочете видалити персонал:\n<b>{name}</b>?\n\n⚠️ <i>Це також зніме всі прив'язки користувачів до цього ПІБ.</i>"

    kb = [
        [types.InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"personnel_delete_yes_{idx}")],
        [types.InlineKeyboardButton(text="❌ Скасувати", callback_data=f"personnel_manage_{idx}")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("personnel_delete_yes_"))
async def personnel_delete_execute(cb: types.CallbackQuery) -> None:
    """Execute personnel deletion.

    Args:
        cb: Callback query with format "personnel_delete_yes_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    personnel = db.get_personnel_names()
    if idx < 0 or idx >= len(personnel):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await personnel_list(cb)

    name = personnel[idx]
    success = db.delete_personnel_name(name)

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)

    if success:
        logger.info(f"👥 {actor} видалив персонал: {name}")
        await cb.answer("✅ Персонал видалено", show_alert=True)
    else:
        await cb.answer("❌ Помилка видалення", show_alert=True)

    await personnel_list(cb)
