import logging

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import ensure_admin_user, actor_name
from keyboards.builders import maintenance_menu, back_to_mnt

router = Router()
logger = logging.getLogger(__name__)


class SetHoursForm(StatesGroup):
    hours = State()


# --- МЕНЮ ТО ---
@router.callback_query(F.data == "mnt_menu")
async def mnt_view(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    st = db.get_state()
    txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
           f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
           f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
           f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")

    try:
        await cb.message.edit_text(txt, reply_markup=maintenance_menu())
    except TelegramBadRequest:
        await cb.answer()


@router.callback_query(F.data == "mnt_oil")
async def mnt_oil(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    user = ensure_admin_user(cb.from_user.id, first_name=cb.from_user.first_name)
    actor = (user[1] if user and user[1] else actor_name(cb.from_user.id, first_name=cb.from_user.first_name))

    db.record_maintenance("oil", actor)
    logger.info(f"🛢 {actor} виконав заміну мастила")
    await cb.answer("✅ Мастило замінено!", show_alert=True)
    await mnt_view(cb)


@router.callback_query(F.data == "mnt_spark")
async def mnt_spark(cb: types.CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    user = ensure_admin_user(cb.from_user.id, first_name=cb.from_user.first_name)
    actor = (user[1] if user and user[1] else actor_name(cb.from_user.id, first_name=cb.from_user.first_name))

    db.record_maintenance("spark", actor)
    logger.info(f"🕯 {actor} виконав заміну свічок")
    await cb.answer("✅ Свічки замінено!", show_alert=True)
    await mnt_view(cb)


@router.callback_query(F.data == "mnt_set_hours")
async def ask_hours(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    st = db.get_state()
    await cb.message.edit_text(f"⏱ Поточний: <b>{st['total_hours']:.1f}</b>\nВведіть нове:", reply_markup=back_to_mnt())
    await state.set_state(SetHoursForm.hours)


@router.message(SetHoursForm.hours)
async def save_hours(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    try:
        val_text = msg.text.replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_mnt())

        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_mnt())

        db.set_total_hours(val)
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        logger.info(f"⏱ {actor} встановив мотогодини: {val}")
        await msg.answer(f"✅ Встановлено: <b>{val} год</b>")

        st = db.get_state()
        txt = (f"🛠 <b>Технічне Обслуговування</b>\n\n"
               f"⏱ Загальний пробіг: <b>{st['total_hours']:.1f} год</b>\n"
               f"🛢 Після заміни мастила: <b>{(st['total_hours'] - st['last_oil']):.1f} год</b>\n"
               f"🕯 Після заміни свічок: <b>{(st['total_hours'] - st['last_spark']):.1f} год</b>")

        await msg.answer(txt, reply_markup=maintenance_menu())
        await state.clear()
    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 100.5)", reply_markup=back_to_mnt())
