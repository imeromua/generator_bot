import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.admin_parts.utils import actor_name
from keyboards.builders import correction_menu, back_to_corr

router = Router()
logger = logging.getLogger(__name__)


class CorrectionForm(StatesGroup):
    fuel = State()
    total_hours = State()
    last_oil = State()
    last_spark = State()


def _block_if_running() -> str | None:
    """Перевіряє чи генератор активний. Якщо так — повертає текст помилки."""
    try:
        st = db.get_state()
        if st.get("status") == "ON":
            return "⛔ Корекції заборонені під час активної зміни. Спочатку натисніть СТОП."
    except Exception:
        return None
    return None


@router.callback_query(F.data == "corr_menu")
async def corr_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    await state.clear()

    block = _block_if_running()
    if block:
        return await cb.answer(block, show_alert=True)

    st = db.get_state()
    txt = (
        "🧮 <b>Корекція</b>\n\n"
        f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
        f"⏱ Мотогодини (total): <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
        f"🛢 Остання заміна мастила: <b>{float(st.get('last_oil', 0.0) or 0.0):.1f} год</b>\n"
        f"🕯 Остання заміна свічок: <b>{float(st.get('last_spark', 0.0) or 0.0):.1f} год</b>\n"
    )

    await cb.message.edit_text(txt, reply_markup=correction_menu())
    await cb.answer()


@router.callback_query(F.data == "corr_fuel_set")
async def corr_fuel_set(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    block = _block_if_running()
    if block:
        return await cb.answer(block, show_alert=True)

    st = db.get_state()
    cur = float(st.get("current_fuel", 0.0) or 0.0)
    await cb.message.edit_text(
        f"⛽️ Поточний: <b>{cur:.1f} л</b>\nВведіть нове значення (літри):",
        reply_markup=back_to_corr(),
    )
    await state.set_state(CorrectionForm.fuel)
    await cb.answer()


@router.message(CorrectionForm.fuel)
async def corr_fuel_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    block = _block_if_running()
    if block:
        await state.clear()
        return await msg.answer(block)

    try:
        val_text = (msg.text or "").replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_corr())
        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_corr())

        db.set_state("current_fuel", str(val))
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        db.add_log("corr_fuel_set", actor, val=str(val))
        logger.info(f"⛽️ {actor} встановив паливо: {val}")

        await state.clear()
        st = db.get_state()
        txt = (
            "✅ Збережено.\n\n"
            "🧮 <b>Корекція</b>\n\n"
            f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
            f"⏱ Мотогодини (total): <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
            f"🛢 Остання заміна мастила: <b>{float(st.get('last_oil', 0.0) or 0.0):.1f} год</b>\n"
            f"🕯 Остання заміна свічок: <b>{float(st.get('last_spark', 0.0) or 0.0):.1f} год</b>\n"
        )
        await msg.answer(txt, reply_markup=correction_menu())

    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 171.0)", reply_markup=back_to_corr())


@router.callback_query(F.data == "corr_total_hours_set")
async def corr_total_hours_set(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    block = _block_if_running()
    if block:
        return await cb.answer(block, show_alert=True)

    st = db.get_state()
    cur = float(st.get("total_hours", 0.0) or 0.0)
    await cb.message.edit_text(
        f"⏱ Поточний total: <b>{cur:.1f} год</b>\nВведіть нове значення (години):",
        reply_markup=back_to_corr(),
    )
    await state.set_state(CorrectionForm.total_hours)
    await cb.answer()


@router.message(CorrectionForm.total_hours)
async def corr_total_hours_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    block = _block_if_running()
    if block:
        await state.clear()
        return await msg.answer(block)

    try:
        val_text = (msg.text or "").replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_corr())
        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_corr())

        db.set_total_hours(val)
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        db.add_log("corr_total_hours_set", actor, val=str(val))
        logger.info(f"⏱ {actor} встановив мотогодини: {val}")

        await state.clear()
        st = db.get_state()
        txt = (
            "✅ Збережено.\n\n"
            "🧮 <b>Корекція</b>\n\n"
            f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
            f"⏱ Мотогодини (total): <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
            f"🛢 Остання заміна мастила: <b>{float(st.get('last_oil', 0.0) or 0.0):.1f} год</b>\n"
            f"🕯 Остання заміна свічок: <b>{float(st.get('last_spark', 0.0) or 0.0):.1f} год</b>\n"
        )
        await msg.answer(txt, reply_markup=correction_menu())

    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 123.5)", reply_markup=back_to_corr())


@router.callback_query(F.data == "corr_last_oil_set")
async def corr_last_oil_set(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    block = _block_if_running()
    if block:
        return await cb.answer(block, show_alert=True)

    st = db.get_state()
    cur = float(st.get("last_oil", 0.0) or 0.0)
    await cb.message.edit_text(
        f"🛢 Поточний last_oil_change: <b>{cur:.1f} год</b>\nВведіть нове значення (мотогодини):",
        reply_markup=back_to_corr(),
    )
    await state.set_state(CorrectionForm.last_oil)
    await cb.answer()


@router.message(CorrectionForm.last_oil)
async def corr_last_oil_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    block = _block_if_running()
    if block:
        await state.clear()
        return await msg.answer(block)

    try:
        val_text = (msg.text or "").replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_corr())
        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_corr())

        db.set_state("last_oil_change", str(val))
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        db.add_log("corr_last_oil_set", actor, val=str(val))
        logger.info(f"🛢 {actor} встановив last_oil_change: {val}")

        await state.clear()
        st = db.get_state()
        txt = (
            "✅ Збережено.\n\n"
            "🧮 <b>Корекція</b>\n\n"
            f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
            f"⏱ Мотогодини (total): <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
            f"🛢 Остання заміна мастила: <b>{float(st.get('last_oil', 0.0) or 0.0):.1f} год</b>\n"
            f"🕯 Остання заміна свічок: <b>{float(st.get('last_spark', 0.0) or 0.0):.1f} год</b>\n"
        )
        await msg.answer(txt, reply_markup=correction_menu())

    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 100.0)", reply_markup=back_to_corr())


@router.callback_query(F.data == "corr_last_spark_set")
async def corr_last_spark_set(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("⛔ Тільки для адмінів", show_alert=True)

    block = _block_if_running()
    if block:
        return await cb.answer(block, show_alert=True)

    st = db.get_state()
    cur = float(st.get("last_spark", 0.0) or 0.0)
    await cb.message.edit_text(
        f"🕯 Поточний last_spark_change: <b>{cur:.1f} год</b>\nВведіть нове значення (мотогодини):",
        reply_markup=back_to_corr(),
    )
    await state.set_state(CorrectionForm.last_spark)
    await cb.answer()


@router.message(CorrectionForm.last_spark)
async def corr_last_spark_save(msg: types.Message, state: FSMContext):
    if msg.from_user.id not in config.ADMIN_IDS:
        await state.clear()
        return await msg.answer("⛔ Тільки для адмінів")

    block = _block_if_running()
    if block:
        await state.clear()
        return await msg.answer(block)

    try:
        val_text = (msg.text or "").replace(",", ".").strip()
        val = float(val_text)

        if val < 0:
            return await msg.answer("❌ Значення не може бути від'ємним", reply_markup=back_to_corr())
        if val > 100000:
            return await msg.answer("❌ Значення занадто велике (максимум 100000)", reply_markup=back_to_corr())

        db.set_state("last_spark_change", str(val))
        actor = actor_name(msg.from_user.id, first_name=msg.from_user.first_name)
        db.add_log("corr_last_spark_set", actor, val=str(val))
        logger.info(f"🕯 {actor} встановив last_spark_change: {val}")

        await state.clear()
        st = db.get_state()
        txt = (
            "✅ Збережено.\n\n"
            "🧮 <b>Корекція</b>\n\n"
            f"⛽️ Поточний залишок палива: <b>{float(st.get('current_fuel', 0.0) or 0.0):.1f} л</b>\n"
            f"⏱ Мотогодини (total): <b>{float(st.get('total_hours', 0.0) or 0.0):.1f} год</b>\n"
            f"🛢 Остання заміна мастила: <b>{float(st.get('last_oil', 0.0) or 0.0):.1f} год</b>\n"
            f"🕯 Остання заміна свічок: <b>{float(st.get('last_spark', 0.0) or 0.0):.1f} год</b>\n"
        )
        await msg.answer(txt, reply_markup=correction_menu())

    except ValueError:
        await msg.answer("❌ Введіть число (наприклад 100.0)", reply_markup=back_to_corr())
