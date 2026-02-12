import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database.db_api as db
from database.models import get_connection, begin_transaction
from handlers.common import show_dash
from handlers.user_parts.utils import ensure_user, get_operator_personnel_name
from keyboards.builders import main_dashboard, drivers_list
from utils.time import now_kiev
from utils.messaging import notify_success, notify_error  # FIX #25

router = Router()


class RefillForm(StatesGroup):
    driver = State()
    liters = State()
    receipt = State()


def _within_work_window(now_t, start_t, end_t) -> bool:
    """Труе якщо now_t всередині [start_t, end_t) вікна.

    Працює для вікон, які НЕ перетинають північ (start<=end) та які перетинають північ.
    """
    if start_t <= end_t:
        return start_t <= now_t < end_t
    # crosses midnight, e.g. 22:00-06:00
    return now_t >= start_t or now_t < end_t


def _refill_allowed_now() -> tuple[bool, str]:
    """Перевіряє чи дозволено прийом палива зараз на основі WORK_START_TIME/WORK_END_TIME.

    Повертає (ok, human_message).
    """
    try:
        now = now_kiev()
        start_t = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        end_t = datetime.strptime(config.WORK_END_TIME, "%H:%M").time()
        if not _within_work_window(now.time(), start_t, end_t):
            return False, (
                f"⛔ Прийом палива заборонено поза робочим часом "
                f"({config.WORK_START_TIME}-{config.WORK_END_TIME}).\n"
                f"Зараз: {now.strftime('%H:%M')}"
            )
        return True, ""
    except Exception:
        # якщо конфіг часу некоректний — не блокуємо
        return True, ""


def _fuel_quick_buttons() -> types.InlineKeyboardMarkup:
    """FIX #21: Швидкі кнопки для вибору кількості палива."""
    kb = [
        [
            types.InlineKeyboardButton(text="20 л", callback_data="fuel_20"),
            types.InlineKeyboardButton(text="40 л", callback_data="fuel_40"),
        ],
        [
            types.InlineKeyboardButton(text="60 л", callback_data="fuel_60"),
            types.InlineKeyboardButton(text="80 л", callback_data="fuel_80"),
        ],
        [
            types.InlineKeyboardButton(text="🔢 Інша кількість", callback_data="fuel_custom"),
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


# --- ЗАПРАВКА ---
@router.callback_query(F.data == "refill_init")
async def refill_start(cb: types.CallbackQuery, state: FSMContext):
    # FIX #21: Only check at init, not at every step
    ok, err = _refill_allowed_now()
    if not ok:
        return await cb.answer(err, show_alert=True)

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
    # FIX #21: No check here - user already started the flow
    driver_name = cb.data.split("_", 1)[1]
    await state.update_data(driver=driver_name)
    await cb.message.edit_text(
        f"Водій: <b>{driver_name}</b>\n🔢 Скільки літрів прийнято?",
        reply_markup=_fuel_quick_buttons()
    )
    await state.set_state(RefillForm.liters)
    await cb.answer()


@router.callback_query(RefillForm.liters, F.data.startswith("fuel_"))
async def refill_quick_amount(cb: types.CallbackQuery, state: FSMContext):
    """FIX #21: Обробка швидких кнопок вибору кількості палива."""
    fuel_type = cb.data.split("_")[1]
    
    if fuel_type == "custom":
        # Користувач хоче ввести вручну
        await cb.message.edit_text(
            f"🔢 Введіть кількість літрів (числом):",
            reply_markup=main_dashboard('admin' if cb.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
        )
        await cb.answer()
        return
    
    # Швидкий вибір: 20, 40, 60, 80
    try:
        liters = float(fuel_type)
    except Exception:
        await cb.answer("⚠️ Помилка вибору кількості", show_alert=True)
        return
    
    await state.update_data(liters=liters)
    await cb.message.edit_text(
        f"Літри: <b>{liters:.0f} л</b>\n🧾 Введіть <b>номер чека</b>:",
        reply_markup=main_dashboard('admin' if cb.from_user.id in config.ADMIN_IDS else 'manager', db.get_state().get('active_shift', 'none'), db.get_today_completed_shifts())
    )
    await state.set_state(RefillForm.receipt)
    await cb.answer()


@router.message(RefillForm.liters)
async def refill_ask_receipt(msg: types.Message, state: FSMContext):
    """Обробка ручного вводу кількості літрів."""
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
                    text=f"Літри: <b>{liters:.1f} л</b>\n🧾 Введіть <b>номер чека</b>:",
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
    # FIX #21: Check again only at final save to catch edge cases
    ok, err = _refill_allowed_now()
    if not ok:
        await state.clear()
        user = ensure_user(msg.from_user.id, msg.from_user.first_name)
        if user:
            # FIX #25: Notify error
            notify_error(msg.from_user.id, "❌ Прийом палива заборонено поза робочим часом")
            await show_dash(msg, user[0], user[1], banner=err)
        else:
            try:
                await msg.answer(err)
            except Exception:
                pass
        return

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

    # FIX #20: Wrap refill in transaction to ensure consistency
    conn = None
    try:
        conn = get_connection()
        begin_transaction(conn)
        
        # Add log entry
        db.add_log("refill", operator_personnel, str(liters), driver, receipt=receipt_num, conn=conn)
        
        # Update fuel state atomically
        db.update_fuel(liters, conn=conn)
        
        conn.commit()
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        
        await state.clear()
        
        # FIX #25: Notify error
        notify_error(msg.from_user.id, f"❌ Помилка збереження заправки: {str(e)[:50]}")
        
        err_banner = f"❌ <b>Помилка збереження заправки</b>\n\n{e}"
        await show_dash(msg, user[0], user[1], banner=err_banner)
        return
        
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    await state.clear()

    # FIX #25: Notify success
    notify_success(
        msg.from_user.id, 
        f"✅ Прийнято {float(liters):.1f} л палива (Водій: {driver}, Чек: {receipt_num})"
    )

    banner = (
        f"✅ <b>Паливо прийнято</b>\n"
        f"🛢 Літри: <b>{float(liters):.1f}</b>\n"
        f"🧾 Чек: <b>{receipt_num}</b>\n"
        f"🚛 Водій: <b>{driver}</b>\n"
        f"👤 Відповідальний: <b>{operator_personnel}</b>"
    )

    await show_dash(msg, user[0], user[1], banner=banner)
