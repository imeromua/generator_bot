from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import config
import database.db_api as db
from keyboards.builders import main_dashboard, drivers_list, back_to_main
from handlers.common import show_dash

router = Router()

class RefillForm(StatesGroup):
    driver = State()
    liters = State()

# --- СТАРТ ---
@router.callback_query(F.data.in_({"m_start", "d_start", "e_start"}))
async def gen_start(cb: types.CallbackQuery):
    st = db.get_state()
    if st['status'] == 'ON': 
        return await cb.answer("⛔ ВЖЕ ПРАЦЮЄ!", show_alert=True)
    
    now = datetime.now(config.KYIV)
    start_time_limit = datetime.strptime(config.WORK_START_TIME, "%H:%M").time()
    if now.time() < start_time_limit:
        return await cb.answer(f"😴 Ще рано! Робота з {config.WORK_START_TIME}", show_alert=True)

    user = db.get_user(cb.from_user.id)
    db.set_state('status', 'ON')
    db.set_state('last_start_time', now.strftime("%H:%M"))
    db.add_log(cb.data, user[1])
    
    await cb.message.delete()
    await cb.message.answer(
        f"✅ <b>{cb.data.upper()}</b> відкрито о {now.strftime('%H:%M')}\n👤 {user[1]}",
        reply_markup=main_dashboard('manager', True)
    )
    await cb.answer()

# --- СТОП ---
@router.callback_query(F.data.in_({"m_end", "d_end", "e_end"}))
async def gen_stop(cb: types.CallbackQuery):
    st = db.get_state()
    if st['status'] == 'OFF': 
        return await cb.answer("⛔ Вже вимкнено.", show_alert=True)
    
    now = datetime.now(config.KYIV)
    try:
        start_dt = datetime.strptime(f"{now.date()} {st['start_time']}", "%Y-%m-%d %H:%M")
        dur = (now.replace(tzinfo=None) - start_dt).total_seconds() / 3600.0
    except:
        dur = 0.0

    user = db.get_user(cb.from_user.id)
    
    db.update_hours(dur)
    fuel_consumed = dur * config.FUEL_CONSUMPTION
    remaining_fuel = db.update_fuel(-fuel_consumed)
    
    db.set_state('status', 'OFF')
    db.add_log(cb.data, user[1])
    
    await cb.message.delete()
    await cb.message.answer(
        f"🏁 <b>Зміну закрито!</b>\n"
        f"⏱ Працював: <b>{dur:.2f} год</b>\n"
        f"📉 Використано: <b>{fuel_consumed:.1f} л</b>\n"
        f"⛽ Залишок: <b>{remaining_fuel:.1f} л</b>\n"
        f"👤 {user[1]}", 
        reply_markup=main_dashboard('manager', False)
    )
    await cb.answer()

# --- ЗАПРАВКА ---
@router.callback_query(F.data == "refill_init")
async def refill_start(cb: types.CallbackQuery, state: FSMContext):
    drivers = db.get_drivers()
    await cb.message.edit_text("🚛 Хто привіз паливо?", reply_markup=drivers_list(drivers))
    await state.set_state(RefillForm.driver)

@router.callback_query(RefillForm.driver, F.data.startswith("drv_"))
async def refill_driver(cb: types.CallbackQuery, state: FSMContext):
    driver_name = cb.data.split("_")[1]
    await state.update_data(driver=driver_name)
    # ТУТ ТЕЖ ДОДАЛИ КНОПКУ СКАСУВАТИ
    await cb.message.edit_text(f"Водій: <b>{driver_name}</b>\n🔢 Скільки літрів прийнято? (Напишіть цифру)", reply_markup=back_to_main())
    await state.set_state(RefillForm.liters)

@router.message(RefillForm.liters)
async def refill_save(msg: types.Message, state: FSMContext):
    try:
        liters = float(msg.text.replace(",", "."))
        data = await state.get_data()
        user = db.get_user(msg.from_user.id)
        
        db.add_log("refill", user[1], str(liters), data['driver'])
        new_balance = db.update_fuel(liters)
        
        await msg.answer(f"✅ Прийнято {liters}л (Водій: {data['driver']})\n⛽ Новий баланс: {new_balance:.1f} л")
        await state.clear()
        
        await show_dash(msg, msg.from_user.id, user[1])
        
    except ValueError:
        await msg.answer("❌ Будь ласка, введіть число (наприклад 50 або 50.5)")

# Кнопка СКАСУВАТИ / НА ГОЛОВНУ
@router.callback_query(F.data == "home")
async def go_home(cb: types.CallbackQuery, state: FSMContext):
    # Обов'язкове очищення стану
    await state.clear()
    
    user = db.get_user(cb.from_user.id)
    await cb.message.delete()
    await show_dash(cb.message, user[0], user[1])