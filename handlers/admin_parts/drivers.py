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
    name = State()


# --- ВОДІЇ ---
@router.callback_query(F.data == "add_driver_start")
async def drv_add(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await cb.message.edit_text("✍️ Введіть прізвище водія:", reply_markup=back_to_admin())
    await state.set_state(AddDriverForm.name)


@router.message(AddDriverForm.name)
async def drv_save(msg: types.Message, state: FSMContext):
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
