from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta

import config
import database.db_api as db
from keyboards.builders import main_dashboard, drivers_list, back_to_main
from handlers.common import show_dash


router = Router()


class RefillForm(StatesGroup):
    driver = State()
    liters = State()
    receipt = State()


def _ensure_user(user_id: int, first_name: str | None = None):
    """Повертає (user_id, full_name) з БД. Якщо адмін без запису — авто-реєструє."""
    user = db.get_user(user_id)
    if user:
        return user

    if user_id in config.ADMIN_IDS:
        name = f"Admin {first_name or ''}".strip()
        if not name:
            name = f"Admin {user_id}"
        db.register_user(user_id, name)
        return db.get_user(user_id)

    return None


def format_hours_hhmm(hours_float: float) -> str:
    """Конвертує години (float) у формат ГГ:ХХ."""
    try:
        h = float(hours_float)
    except Exception:
        h = 0.0

    sign = "-" if h < 0 else ""
    h = abs(h)

    total_minutes = int(round(h * 60.0))
    hh = total_minutes // 60
    mm = total_minutes % 60

    return f"{sign}{hh:02d}:{mm:02d}"


def _safe_delete(message: types.Message):
    async def _inner():
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        except Exception:
            pass
    return _inner()


# --- СТАРТ ---
@router.callback_query(F.data.in_({"m_start", "d_start", "e_start", "x_start"}))
async def gen_start(cb: types.CallbackQuery):
    st = db.get_state()
    if st['status'] == 'ON':
        return await cb.answer(
            f"⛔ ВЖЕ ПРАЦЮЄ! (Активна зміна: {st.get('active_shift', 'Невідома')})",
            show_alert=True
        )

    shift_code = cb.data.split("_")[0]
    completed = db.get_today_completed_shifts()
    if shift_code in completed:
        return await cb.answer("⛔ Ця зміна вже відпрацьована сьогодні!", show_alert=True)

    now = datetime.now(config.KYIV)

    if cb.data != "x_start":
        start_time_limit = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
        if now.time() < start_time_limit:
            return await cb.answer(f"😴 Ще рано! Робота з {config.WORK_START_TIME}", show_alert=True)

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    db.set_state('status', 'ON')
    db.set_state('active_shift', cb.data)
    db.set_state('last_start_time', now.strftime("%H:%M"))
    db.set_state('last_start_date', now.strftime("%Y-%m-%d"))
    db.add_log(cb.data, user[1])

    names = {
        "m_start": "🌅 РАНОК",
        "d_start": "☀️ ДЕНЬ",
        "e_start": "🌙 ВЕЧІР",
        "x_start": "⚡ ЕКСТРА"
    }
    pretty_name = names.get(cb.data, cb.data)

    await _safe_delete(cb.message)

    role = 'admin' if cb.from_user.id in config.ADMIN_IDS else 'manager'

    await cb.message.answer(
        f"✅ <b>{pretty_name}</b> відкрито о {now.strftime('%H:%M')}\n👤 {user[1]}",
        reply_markup=main_dashboard(role, cb.data, completed)
    )

    await cb.answer()


# --- СТОП ---
@router.callback_query(F.data.in_({"m_end", "d_end", "e_end", "x_end"}))
async def gen_stop(cb: types.CallbackQuery):
    st = db.get_state()
    if st['status'] == 'OFF':
        return await cb.answer("⛔ Вже вимкнено.", show_alert=True)

    valid_pairs = {
        "m_end": "m_start",
        "d_end": "d_start",
        "e_end": "e_start",
        "x_end": "x_start"
    }

    current_active = st.get('active_shift', 'none')

    if current_active in valid_pairs.values() and current_active != valid_pairs.get(cb.data):
        names = {"m_start": "РАНОК", "d_start": "ДЕНЬ", "e_start": "ВЕЧІР", "x_start": "ЕКСТРА"}
        opened_name = names.get(current_active, current_active)
        return await cb.answer(
            f"⛔ Помилка! Зараз активний {opened_name}.\nНатисніть відповідну кнопку СТОП.",
            show_alert=True
        )

    now = datetime.now(config.KYIV)

    # Виправлення проблеми переходу через північ
    try:
        start_date_str = st.get('start_date', '')
        start_time_str = st['start_time']

        if start_date_str:
            start_dt = datetime.strptime(f"{start_date_str} {start_time_str}", "%Y-%m-%d %H:%M")
        else:
            start_dt = datetime.strptime(f"{now.date()} {start_time_str}", "%Y-%m-%d %H:%M")
            if now.time() < datetime.strptime(start_time_str, "%H:%M").time():
                start_dt = start_dt - timedelta(days=1)

        start_dt = config.KYIV.localize(start_dt.replace(tzinfo=None))
        dur = (now - start_dt).total_seconds() / 3600.0

        if dur < 0 or dur > 24:
            dur = 0.0

    except Exception as e:
        import logging
        logging.error(f"Помилка розрахунку тривалості: {e}")
        dur = 0.0

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        return await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)

    # Таблиця = еталон. Тут тільки рахуємо, але НЕ змінюємо state/current_fuel в БД.
    fuel_consumed = dur * config.FUEL_CONSUMPTION
    try:
        canonical_fuel = float(st.get('current_fuel', 0.0) or 0.0)
    except Exception:
        canonical_fuel = 0.0
    remaining_est = canonical_fuel - fuel_consumed

    db.set_state('status', 'OFF')
    db.set_state('active_shift', 'none')
    db.add_log(cb.data, user[1])

    dur_hhmm = format_hours_hhmm(dur)

    await _safe_delete(cb.message)

    role = 'admin' if cb.from_user.id in config.ADMIN_IDS else 'manager'
    completed = db.get_today_completed_shifts()

    await cb.message.answer(
        f"🏁 <b>Зміну закрито!</b>\n"
        f"⏱️ Працював: <b>{dur_hhmm}</b>\n"
        f"📉 Використано (розрах.): <b>{fuel_consumed:.1f} л</b>\n"
        f"⛽️ Залишок (за таблицею - розрах.): <b>{remaining_est:.1f} л</b>\n"
        f"👤 {user[1]}",
        reply_markup=main_dashboard(role, 'none', completed)
    )

    await cb.answer()


# --- ЗАПРАВКА ---
@router.callback_query(F.data == "refill_init")
async def refill_start(cb: types.CallbackQuery, state: FSMContext):
    drivers = db.get_drivers()
    if not drivers:
        return await cb.answer("⚠️ Спочатку додайте водіїв в адмін-панелі", show_alert=True)
    await cb.message.edit_text("🚛 Хто привіз паливо?", reply_markup=drivers_list(drivers))
    await state.set_state(RefillForm.driver)


@router.callback_query(RefillForm.driver, F.data.startswith("drv_"))
async def refill_driver(cb: types.CallbackQuery, state: FSMContext):
    driver_name = cb.data.split("_", 1)[1]
    await state.update_data(driver=driver_name)
    await cb.message.edit_text(
        f"Водій: <b>{driver_name}</b>\n🔢 Скільки літрів прийнято? (Напишіть цифру)",
        reply_markup=back_to_main()
    )
    await state.set_state(RefillForm.liters)


@router.message(RefillForm.liters)
async def refill_ask_receipt(msg: types.Message, state: FSMContext):
    try:
        liters_text = msg.text.replace(",", ".").strip()
        liters = float(liters_text)

        if liters <= 0:
            return await msg.answer("❌ Кількість літрів має бути більше 0")

        if liters > 500:
            return await msg.answer("❌ Кількість літрів занадто велика (максимум 500л)")

        await state.update_data(liters=liters)
        await msg.answer("🧾 Введіть <b>номер чека</b>:", reply_markup=back_to_main())
        await state.set_state(RefillForm.receipt)
    except ValueError:
        await msg.answer("❌ Будь ласка, введіть число (наприклад 50 або 50.5)")


@router.message(RefillForm.receipt)
async def refill_save(msg: types.Message, state: FSMContext):
    receipt_num = msg.text.strip()

    if not receipt_num:
        return await msg.answer("❌ Номер чека не може бути порожнім")

    if len(receipt_num) > 50:
        return await msg.answer("❌ Номер чека занадто довгий (максимум 50 символів)")

    data = await state.get_data()
    liters = data['liters']
    driver = data['driver']

    user = _ensure_user(msg.from_user.id, msg.from_user.first_name)
    if not user:
        await state.clear()
        return await msg.answer("⚠️ Спочатку натисніть /start")

    log_val = f"{liters}|{receipt_num}"
    db.add_log("refill", user[1], log_val, driver)

    # Таблиця = еталон. Тут НЕ змінюємо current_fuel в БД, лише фіксуємо подію.
    st = db.get_state()
    try:
        canonical_fuel = float(st.get('current_fuel', 0.0) or 0.0)
    except Exception:
        canonical_fuel = 0.0

    await msg.answer(
        f"✅ Записано: <b>{liters} л</b>\n"
        f"🧾 Чек: <b>{receipt_num}</b>\n"
        f"🚛 Водій: {driver}\n"
        f"ℹ️ Залишок (за таблицею): <b>{canonical_fuel:.1f} л</b>"
    )

    await state.clear()
    await show_dash(msg, msg.from_user.id, user[1])


@router.callback_query(F.data == "home")
async def go_home(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = _ensure_user(cb.from_user.id, cb.from_user.first_name)
    if not user:
        await cb.answer("⚠️ Спочатку натисніть /start", show_alert=True)
        return

    await _safe_delete(cb.message)
    await show_dash(cb.message, user[0], user[1])
    await cb.answer()
