import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from handlers.common import show_dash
from handlers.user_parts.utils import ensure_user, get_operator_personnel_name
from keyboards.builders import main_dashboard, drivers_list

router = Router()


class RefillForm(StatesGroup):
    driver = State()
    liters = State()
    receipt = State()


# --- ЗАПРАВКА ---
@router.callback_query(F.data == "refill_init")
async def refill_start(cb: types.CallbackQuery, state: FSMContext):
    operator_personnel = get_operator_personnel_name(cb.from_user.id)
    if not operator_personnel:
        return await cb.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.", show_alert=True)

    drivers = db.get_drivers()
    if not drivers:
        return await cb.answer("⚠️ Спочатку додайте водіїв в адмін-панелі", show_alert=True)

    # запам'ятовуємо повідомлення "вікна"
    await state.update_data(ui_chat_id=cb.message.chat.id, ui_message_id=cb.message.message_id)

    await cb.message.edit_text("🚛 Хто привіз паливо?", reply_markup=drivers_list(drivers))
    await state.set_state(RefillForm.driver)
    await cb.answer()


@router.callback_query(RefillForm.driver, F.data.startswith("drv_"))
async def refill_driver(cb: types.CallbackQuery, state: FSMContext):
    driver_name = cb.data.split("_", 1)[1]
    await state.update_data(driver=driver_name)
    await cb.message.edit_text(
        f"Водій: <b>{driver_name}</b>\n🔢 Скільки літрів прийнято? (Напишіть цифру)",
        reply_markup=main_dashboard('admin' if cb.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
    )
    await state.set_state(RefillForm.liters)
    await cb.answer()


@router.message(RefillForm.liters)
async def refill_ask_receipt(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = int(data.get("ui_chat_id", msg.chat.id))
    message_id = int(data.get("ui_message_id", 0))

    try:
        liters_text = (msg.text or "").replace(",", ".").strip()
        liters = float(liters_text)

        if liters <= 0 or liters > 500:
            raise ValueError

        await state.update_data(liters=liters)

        if message_id:
            try:
                await msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="🧾 Введіть <b>номер чека</b>:",
                    reply_markup=main_dashboard('admin' if msg.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e).lower():
                    raise

        await state.set_state(RefillForm.receipt)

    except Exception:
        if message_id:
            try:
                await msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="❌ Введіть кількість літрів числом (1..500).",
                    reply_markup=main_dashboard('admin' if msg.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
                )
            except Exception:
                pass


@router.message(RefillForm.receipt)
async def refill_save(msg: types.Message, state: FSMContext):
    receipt_num = (msg.text or "").strip()

    data = await state.get_data()
    chat_id = int(data.get("ui_chat_id", msg.chat.id))
    message_id = int(data.get("ui_message_id", 0))

    if (not receipt_num) or (len(receipt_num) > 50):
        err_txt = "❌ Введіть коректний номер чека (1..50 символів)."
        if message_id:
            try:
                await msg.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=err_txt,
                    reply_markup=main_dashboard('admin' if msg.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
                )
            except Exception:
                pass
        else:
            try:
                await msg.answer(err_txt)
            except Exception:
                pass
        # Важливо: стан не чистимо, користувач лишається у вводі чека
        return

    liters = data.get('liters')
    driver = data.get('driver')

    user = ensure_user(msg.from_user.id, msg.from_user.first_name)
    if not user:
        await state.clear()
        try:
            await msg.answer("⚠️ Спочатку натисніть /start")
        except Exception:
            pass
        return

    operator_personnel = get_operator_personnel_name(msg.from_user.id)
    if not operator_personnel:
        await state.clear()
        try:
            await msg.answer("⚠️ Нема прив'язки до персоналу. Адмінка → Персонал.")
        except Exception:
            pass
        return

    log_val = f"{liters}|{receipt_num}"
    db.add_log("refill", operator_personnel, log_val, driver)

    if db.sheet_is_offline():
        try:
            db.update_fuel(float(liters or 0.0))
        except Exception:
            pass

    await state.clear()

    banner = (
        f"✅ <b>Паливо прийнято</b>\n"
        f"🛢 Літри: <b>{float(liters):.1f}</b>\n"
        f"🧾 Чек: <b>{receipt_num}</b>\n"
        f"🚛 Водій: <b>{driver}</b>\n"
        f"👤 Відповідальний: <b>{operator_personnel}</b>"
    )

    await show_dash(msg, user[0], user[1], banner=banner)
