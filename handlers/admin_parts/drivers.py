"""Drivers management handler.

Complete CRUD interface for fuel delivery drivers:
- List all drivers
- Add new driver
- Edit driver name
- Delete driver with confirmation
"""

import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name
from keyboards.builders import back_to_admin, after_add_menu

router = Router()
logger = logging.getLogger(__name__)


class AddDriverForm(StatesGroup):
    """FSM states for adding new driver."""
    name = State()


class EditDriverForm(StatesGroup):
    """FSM states for editing driver."""
    old_name = State()
    new_name = State()


# --- ВОДІЇ: МЕНЮ ---
@router.callback_query(F.data == "drivers_menu")
async def drivers_menu(cb: types.CallbackQuery) -> None:
    """Display drivers management menu.

    Args:
        cb: Callback query
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    txt = "🚛 <b>Управління водіями</b>\n\nОберіть дію:"

    kb = [
        [types.InlineKeyboardButton(text="📝 Перелік водіїв", callback_data="drivers_list")],
        [types.InlineKeyboardButton(text="➕ Додати водія", callback_data="add_driver_start")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_home")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- ПЕРЕЛІК ВОДІЇВ ---
@router.callback_query(F.data == "drivers_list")
async def drivers_list(cb: types.CallbackQuery) -> None:
    """Display list of all drivers.

    Shows up to 40 drivers with option to manage each.

    Args:
        cb: Callback query
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    drivers = db.get_drivers()

    if not drivers:
        txt = "🚛 <b>Список водіїв</b>\n\n⚠️ Список пустий.\n\n<i>Додайте водіїв або запустіть синхронізацію.</i>"
        kb = [
            [types.InlineKeyboardButton(text="➕ Додати водія", callback_data="add_driver_start")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="drivers_menu")],
        ]
        return await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

    txt = f"🚛 <b>Список водіїв</b> ({len(drivers)})\n\nОберіть водія для редагування або видалення:"

    kb = []
    for idx, driver in enumerate(drivers[:40]):
        kb.append([types.InlineKeyboardButton(
            text=f"👤 {driver}",
            callback_data=f"driver_manage_{idx}"
        )])

    kb.append([types.InlineKeyboardButton(text="➕ Додати водія", callback_data="add_driver_start")])
    kb.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="drivers_menu")])

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- УПРАВЛІННЯ ВОДІЄМ ---
@router.callback_query(F.data.startswith("driver_manage_"))
async def driver_manage(cb: types.CallbackQuery) -> None:
    """Display management options for specific driver.

    Args:
        cb: Callback query with format "driver_manage_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    drivers = db.get_drivers()
    if idx < 0 or idx >= len(drivers):
        await cb.answer("⚠️ Список оновився. Поверніться.", show_alert=True)
        return await drivers_list(cb)

    driver_name = drivers[idx]

    txt = f"👤 <b>Водій: {driver_name}</b>\n\nОберіть дію:"

    kb = [
        [types.InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"driver_edit_{idx}")],
        [types.InlineKeyboardButton(text="🗑️ Видалити", callback_data=f"driver_delete_{idx}")],
        [types.InlineKeyboardButton(text="🔙 Назад", callback_data="drivers_list")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


# --- ДОДАТИ ВОДІЯ ---
@router.callback_query(F.data == "add_driver_start")
async def drv_add(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Start driver addition process.

    Args:
        cb: Callback query
        state: FSM context
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("✍️ Введіть прізвище водія:", reply_markup=back_to_admin())
    await state.set_state(AddDriverForm.name)


@router.message(AddDriverForm.name)
async def drv_save(msg: types.Message, state: FSMContext) -> None:
    """Save new driver.

    Args:
        msg: Message with driver name
        state: FSM context
    """
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    driver_name = msg.text.strip()

    if not driver_name:
        return await msg.answer("❌ Ім'я не може бути порожнім", reply_markup=back_to_admin())

    if len(driver_name) > 50:
        return await msg.answer("❌ Ім'я занадто довге (максимум 50 символів)", reply_markup=back_to_admin())

    success = db.add_driver(driver_name)

    actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)

    if success:
        logger.info(f"🚛 {actor} додав водія: {driver_name}")
        await msg.answer(f"✅ {driver_name} доданий.", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Водій {driver_name} вже існує.", reply_markup=after_add_menu())

    await state.clear()


# --- РЕДАГУВАТИ ВОДІЯ ---
@router.callback_query(F.data.startswith("driver_edit_"))
async def driver_edit_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Start driver edit process.

    Args:
        cb: Callback query with format "driver_edit_INDEX"
        state: FSM context
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    drivers = db.get_drivers()
    if idx < 0 or idx >= len(drivers):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await drivers_list(cb)

    old_name = drivers[idx]

    await state.update_data(old_name=old_name)
    await state.set_state(EditDriverForm.new_name)

    txt = f"✏️ <b>Редагування водія</b>\n\nПоточне ім'я: <b>{old_name}</b>\n\nВведіть нове ім'я:"

    await cb.message.edit_text(txt, reply_markup=back_to_admin())


@router.message(EditDriverForm.new_name)
async def driver_edit_save(msg: types.Message, state: FSMContext) -> None:
    """Save edited driver name.

    Args:
        msg: Message with new driver name
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
        return await msg.answer("❌ Ім'я не може бути порожнім", reply_markup=back_to_admin())

    if len(new_name) > 50:
        return await msg.answer("❌ Ім'я занадто довге (максимум 50 символів)", reply_markup=back_to_admin())

    success = db.update_driver(old_name, new_name)

    actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)

    if success:
        logger.info(f"🚛 {actor} змінив водія: {old_name} → {new_name}")
        await msg.answer(f"✅ Змінено: {old_name} → {new_name}", reply_markup=after_add_menu())
    else:
        await msg.answer(f"⚠️ Водій {new_name} вже існує або помилка оновлення.", reply_markup=after_add_menu())

    await state.clear()


# --- ВИДАЛИТИ ВОДІЯ ---
@router.callback_query(F.data.startswith("driver_delete_"))
async def driver_delete_confirm(cb: types.CallbackQuery) -> None:
    """Show driver deletion confirmation.

    Args:
        cb: Callback query with format "driver_delete_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    drivers = db.get_drivers()
    if idx < 0 or idx >= len(drivers):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await drivers_list(cb)

    driver_name = drivers[idx]

    txt = f"⚠️ <b>Підтвердження видалення</b>\n\nВи впевнені, що хочете видалити водія:\n<b>{driver_name}</b>?"

    kb = [
        [types.InlineKeyboardButton(text="✅ Так, видалити", callback_data=f"driver_delete_yes_{idx}")],
        [types.InlineKeyboardButton(text="❌ Скасувати", callback_data=f"driver_manage_{idx}")],
    ]

    await cb.message.edit_text(txt, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("driver_delete_yes_"))
async def driver_delete_execute(cb: types.CallbackQuery) -> None:
    """Execute driver deletion.

    Args:
        cb: Callback query with format "driver_delete_yes_INDEX"
    """
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    try:
        idx = int(cb.data.split("_")[-1])
    except Exception:
        return await cb.answer("❌ Помилка ID", show_alert=True)

    drivers = db.get_drivers()
    if idx < 0 or idx >= len(drivers):
        await cb.answer("⚠️ Список оновився.", show_alert=True)
        return await drivers_list(cb)

    driver_name = drivers[idx]
    success = db.delete_driver(driver_name)

    actor = actor_name(cb.from_user.id, first_name=cb.from_user.first_name)

    if success:
        logger.info(f"🚛 {actor} видалив водія: {driver_name}")
        await cb.answer("✅ Водія видалено", show_alert=True)
    else:
        await cb.answer("❌ Помилка видалення", show_alert=True)

    await drivers_list(cb)
